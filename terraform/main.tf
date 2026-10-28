locals {
  role   = "${var.name}-lambda-role"
  server = "${path.module}/../src/server"
  # the image tag is the content hash of src/server: a change there builds and pushes both images
  image_tag  = substr(sha256(join("", [for f in sort(fileset(local.server, "**")) : filesha256("${local.server}/${f}")])), 0, 16)
  image_repo = aws_ecr_repository.server.repository_url
  image_uri  = "${local.image_repo}:${local.image_tag}-${var.architecture}" # the one this deployment runs
  registry   = split("/", aws_ecr_repository.server.repository_url)[0]
  profile    = var.aws_profile != "" ? "--profile ${var.aws_profile}" : ""
  vault_addr = trimsuffix(aws_lambda_function_url.server.function_url, "/")
}

data "aws_caller_identity" "me" {}

# ---------------- storage: Vault's s3 backend (Vault encrypts everything before it is written) ----------------
resource "aws_s3_bucket" "data" {
  bucket        = "${var.name}-${data.aws_caller_identity.me.account_id}" # global name; the account id keeps it unique
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled" # a safety net for overwritten objects, not Vault's KV versions
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------- the seal: Vault's root key is wrapped by this KMS key (auto-unseal, $1 / month) ----------------
resource "aws_kms_key" "seal" {
  description             = "${var.name}: Vault auto-unseal"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "seal" {
  name          = "alias/${var.name}-seal"
  target_key_id = aws_kms_key.seal.key_id
}

# ---------------- the image: official Vault + Lambda Web Adapter (src/server/Dockerfile) ----------------
resource "aws_ecr_repository" "server" {
  name         = var.name
  force_delete = true # destroy must work
}

resource "aws_ecr_lifecycle_policy" "server" {
  repository = aws_ecr_repository.server.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 10 images (5 builds x 2 architectures)"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# builds and pushes both architectures on this machine (Docker running, AWS CLI for the ECR login), only when
# src/server changes: switching var.architecture later needs no rebuild
resource "terraform_data" "image" {
  triggers_replace = [local.image_tag]
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      aws ecr get-login-password --region ${var.region} ${local.profile} | docker login --username AWS --password-stdin ${local.registry}
      docker buildx build --platform linux/arm64 --provenance=false -t ${local.image_repo}:${local.image_tag}-arm64 --push ${local.server}
      docker buildx build --platform linux/amd64 --provenance=false -t ${local.image_repo}:${local.image_tag}-x86_64 --push ${local.server}
    EOT
  }
}

# ---------------- IAM: one role, least privilege ----------------
resource "aws_iam_role" "lambda" {
  name = local.role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.role}-policy"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.data.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.data.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:DescribeKey"]
        Resource = aws_kms_key.seal.arn
      },
    ]
  })
}

# ---------------- the service: one Lambda + Function URL (Vault API and Vault UI) ----------------
resource "aws_lambda_function" "server" {
  function_name = "${var.name}-lambda"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  architectures = [var.architecture]
  timeout       = 30
  memory_size   = var.memory_size

  # one Vault process at a time: the s3 storage backend has no lock, two writers would corrupt it.
  # A request that arrives while it is busy gets 429 (concurrency handling: next phase).
  reserved_concurrent_executions = 1

  environment {
    variables = {
      AWS_S3_BUCKET            = aws_s3_bucket.data.bucket
      VAULT_AWSKMS_SEAL_KEY_ID = aws_kms_key.seal.key_id
    }
  }

  depends_on = [terraform_data.image]
}

# NONE: the URL is public and Vault's own tokens are the gate (as on an EC2 Vault behind a load balancer).
# A public URL needs BOTH permission statements (AWS requirement since Oct 2025).
resource "aws_lambda_function_url" "server" {
  function_name      = aws_lambda_function.server.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.server.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke" {
  statement_id             = "AllowPublicFunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.server.function_name
  principal                = "*"
  invoked_via_function_url = true
}

# ---------------- where `lambdavault output / init` find this deployment (no repo needed on the laptop) ----------------
resource "aws_ssm_parameter" "vault_addr" {
  name  = "/${var.name}/vault_addr"
  type  = "String"
  value = local.vault_addr
}

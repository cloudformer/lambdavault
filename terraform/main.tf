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

# ---------------- storage: Vault's s3 backend (Vault encrypts everything before it is written; new buckets
# are private and SSE-S3 encrypted by AWS default, so neither is restated here) ----------------
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

# ---------------- the seal: Vault's root key is wrapped by this KMS key (auto-unseal, $1 / month, hourly) ----------------
resource "aws_kms_key" "seal" {
  description             = "${var.name}: Vault auto-unseal"
  deletion_window_in_days = 7
  enable_key_rotation     = true
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
# src/server changes: switching var.architecture later needs no rebuild. The login goes to a throw-away
# DOCKER_CONFIG, so whatever credential store ~/.docker/config.json names (ecr-login, osxkeychain, desktop)
# is neither used nor changed; the current context's daemon and the installed CLI plugins still are.
resource "terraform_data" "image" {
  triggers_replace = [local.image_tag]
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      export DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
      export DOCKER_CONFIG="$(mktemp -d)"
      trap 'rm -rf "$DOCKER_CONFIG"' EXIT
      echo '{}' > "$DOCKER_CONFIG/config.json"
      [ -d "$HOME/.docker/cli-plugins" ] && ln -s "$HOME/.docker/cli-plugins" "$DOCKER_CONFIG/cli-plugins"
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

# ---- deploy credentials ----
variable "region" {
  type    = string
  default = "us-east-2"
}

variable "aws_profile" {
  description = "Local AWS CLI profile to use (also for the ECR login of the image push); \"\" = default credential chain"
  type        = string
  default     = ""
}

variable "assume_role_arn" {
  description = "Deploy role to assume; \"\" = none. Pick this OR aws_profile."
  type        = string
  default     = ""

  validation {
    condition     = !(var.assume_role_arn != "" && var.aws_profile != "")
    error_message = "Set either aws_profile or assume_role_arn, not both."
  }
}

# ---- app ----
variable "env" {
  description = "Environment label (tags)"
  type        = string
  default     = "dev"
}

variable "name" {
  description = "Deployment name: resources are <name>-lambda, <name>-<account id> (bucket), <name> (ECR)"
  type        = string
  default     = "lambdavault"
}

variable "architecture" {
  description = "The architecture this deployment runs: arm64 (Graviton, ~20% cheaper) or x86_64; both images are always built"
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86_64"], var.architecture)
    error_message = "architecture must be arm64 or x86_64."
  }
}

variable "memory_size" {
  description = "Lambda memory in MB (CPU scales with it; Vault starts faster with more)"
  type        = number
  default     = 1024
}

variable "force_destroy" {
  description = "Let `destroy` delete the bucket with all of Vault's data in it. Keep false for real secrets."
  type        = bool
  default     = false
}

# The deployment is the published module: cloudformer/infra/aws//modules/lambdavault on the Terraform Registry,
# which deploys a released lambdavault from PyPI (lambdavault_version, default: the version the module was tested
# with). Docker must be running: apply builds and pushes the Vault image when it changed.
data "aws_caller_identity" "me" {}

module "lambdavault" {
  source  = "cloudformer/infra/aws//modules/lambdavault"
  version = "0.2.3"
  # lambdavault_version = "X.Y.Z" # unset: the lambdavault release this module version ships with; set only to deploy another one

  project_name  = var.project_name
  bucket        = "${var.project_name}-${data.aws_caller_identity.me.account_id}" # the existing bucket keeps Vault's data
  seal          = var.seal                                                        # an initialized vault keeps its seal: switching needs a seal migration
  architecture  = var.architecture
  memory_size   = var.memory_size
  force_destroy = var.force_destroy
}

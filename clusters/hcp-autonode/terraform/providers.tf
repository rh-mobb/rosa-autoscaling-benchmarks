provider "aws" {
  region = var.region
  default_tags {
    tags = local.tags
  }
}

provider "rhcs" {
  url = "https://api.openshift.com"
}

provider "shell" {
  interpreter           = ["/bin/sh", "-c"]
  enable_parallelism    = false
  sensitive_environment = {}
}

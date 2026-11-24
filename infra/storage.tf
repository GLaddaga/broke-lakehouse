# Tigris: the data bucket, and one key per role, each scoped by an IAM policy
# to that bucket only. Tigris's own provider manages buckets but not keys, so
# keys and policies go through the AWS provider against Tigris's IAM
# emulation, where a "user" is an access key: the key ID for policies, the
# key's name on create. The admin key that runs this should have "Default
# allowed operations" off, so a key made here can do only what its policy says.

resource "tigris_bucket" "data" {
  bucket               = local.lakehouse_name
  default_storage_tier = "STANDARD"
  location {
    type = "global"
  }
  lifecycle {
    precondition {
      condition     = can(regex("^[a-z][a-z0-9-]{2,40}$", local.lakehouse_name))
      error_message = "lakehouse.name in project.yaml: lowercase letters, digits and dashes, a valid bucket name."
    }
  }
}

# Tigris reports `status` as `active`, AWS's spelling is `Active`, and the
# provider accepts only the latter, so every plan would "update" it. Status is
# never changed here (rotating replaces the key), so it's ignored.
resource "aws_iam_access_key" "runner" {
  user = "${local.lakehouse_name}-runner"
  lifecycle {
    ignore_changes = [status]
  }
}

resource "aws_iam_access_key" "reader" {
  user = "${local.lakehouse_name}-reader"
  lifecycle {
    ignore_changes = [status]
  }
}

locals {
  bucket_arn = "arn:aws:s3:::${tigris_bucket.data.bucket}"
}

# Everything DuckLake, dlt and `ops purge` do on objects. No bucket-level
# writes: the bucket itself belongs to tofu.
resource "aws_iam_policy" "runner" {
  name = "${local.lakehouse_name}-runner"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:ListBucketMultipartUploads"]
        Resource = local.bucket_arn
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject",
        "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
        Resource = "${local.bucket_arn}/*"
      },
    ]
  })
}

resource "aws_iam_policy" "reader" {
  name = "${local.lakehouse_name}-reader"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = local.bucket_arn },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${local.bucket_arn}/*" },
    ]
  })
}

# WORKAROUND, remove when Tigris offers a native way (@docs/roadmap.md).
#
# The attachment is a boto3 call, not a resource, because no provider can make it:
# - aws_iam_user_policy_attachment: Tigris's policy ARNs carry the org ID
#   (`to_…`) where AWS has a 12-digit account, and the AWS provider rejects the
#   ARN before sending the request.
# - aws_iam_user_policy (inline): Tigris answers PutUserPolicy with 501.
# - tigrisdata/tigris: no resource for keys or policies.
# Replace this with a provider resource once Tigris adds key policies or bucket
# roles to its provider, or the AWS provider accepts non-AWS ARNs.
#
# Costs: `plan` can't see an attachment removed by hand, and the dev image
# (python, boto3) plus the admin key from .env.tofu must be where tofu runs.
# A change to the key or the policy replaces this: detach, then attach.
resource "terraform_data" "policy_attachment" {
  for_each = {
    runner = { key = aws_iam_access_key.runner.id, policy = aws_iam_policy.runner.arn }
    reader = { key = aws_iam_access_key.reader.id, policy = aws_iam_policy.reader.arn }
  }
  # The script rides in `input` because a destroy provisioner may only read `self`.
  input            = merge(each.value, { script = local.tigris_iam })
  triggers_replace = each.value

  provisioner "local-exec" {
    interpreter = ["python", "-c"]
    command     = self.input.script
    environment = { ACTION = "attach", KEY = self.input.key, POLICY = self.input.policy }
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["python", "-c"]
    command     = self.input.script
    environment = { ACTION = "detach", KEY = self.input.key, POLICY = self.input.policy }
  }
}

locals {
  # AttachUserPolicy / DetachUserPolicy against Tigris's IAM endpoint. In
  # Tigris, the "user" is the access key ID.
  tigris_iam = <<-PY
    import os, boto3
    iam = boto3.client("iam", endpoint_url="https://iam.storage.dev", region_name="auto")
    getattr(iam, os.environ["ACTION"] + "_user_policy")(
        UserName=os.environ["KEY"], PolicyArn=os.environ["POLICY"])
    print(os.environ["ACTION"] + "ed", os.environ["POLICY"].rsplit("/", 1)[-1])
  PY
}

# aws-cdk-bom — Xirokampi Data Platform: Construct BOM Spike

This spike explores how to verify that a deployed CloudFormation stack was built
from **approved, versioned Xirokampi constructs** — a Bill of Materials (BOM).

The constructs (`FooConstruct`, `BarConstruct`) create SSM parameters as
placeholder resources — in practice they would create SNS topics, S3 buckets,
Glue jobs, or any other AWS resources. The BOM mechanism is independent of what
resources a construct creates.

## Quick start

```bash
make install   # install all workspace packages via uv
make test      # run unit tests
make synth     # synthesise and print the CloudFormation template
make deploy    # deploy to AWS
make bom       # query the live BOM from the deployed stack
```

---

## How it works

### The version flow: from pyproject.toml → CloudFormation

Each Xirokampi construct is its own Python package. The version lives in exactly
one place — `pyproject.toml` — and propagates automatically at import time:

```
packages/xirokampi-utils/pyproject.toml
  [project]
  name    = "xirokampi-utils"
  version = "1.0.0"            ← single source of truth
        │
        │  uv sync  (installs the package into .venv)
        ▼
  importlib.metadata.version("xirokampi-utils")  → "1.0.0"
        │
        ▼
  XirokampiConstruct.__init__  (base class, zero boilerplate in subclass)
    pkg  = type(self).__module__.split(".")[0].replace("_", "-")
           # "xirokampi_utils" → "xirokampi-utils"
    ver  = importlib.metadata.version(pkg)  → "1.0.0"
    self.construct_id = "FooConstruct@1.0.0"
        │
        ├──► Tags.of(self).add("xirokampi:construct", "FooConstruct@1.0.0")
        │         every AWS resource created by FooConstruct carries this tag
        │         (visible in console, Cost Explorer, AWS Config)
        │
        └──► BomAspect.visit(stack)  (runs at synth time)
                  walks node.node.find_all()
                  finds every XirokampiConstruct in the tree
                        │
                        ▼
              stack.template_options.metadata = {
                  "BOM": {
                      "Constructs": [
                          {"blueprint": "FooConstruct@1.0.0", ...},
                          {"blueprint": "BarConstruct@2.1.1", ...}
                      ],
                      "Count": 2
                  }
              }
                        │
                        ▼
              CloudFormation template  ──►  deployed stack
              (Template tab in console)      (make bom queries this)
```

### Bumping a version

Edit `pyproject.toml`, re-sync, re-deploy — nothing else to touch:

```
1. packages/xirokampi-utils/pyproject.toml:  version = "1.0.0" → "1.1.0"
2. make install          # uv rebuilds and reinstalls the package
3. XirokampiConstruct base class re-derives construct_id at import time
                         → "FooConstruct@1.1.0", "BarConstruct@1.1.0"
4. make deploy           # BOM in the live template shows "1.1.0"
                         # xirokampi:construct tag on every resource updated
```

### BOM enforcement (validation)

`BomAspect` is initialised with a set of approved class objects. If any
`XirokampiConstruct` in the stack is not in that set, synthesis raises
immediately — before any AWS API call is made.

```
BomAspect(approved={FooConstruct, BarConstruct})

  app.synth()
    └── BomAspect.visit(Stack)
          ├── finds NaughtyConstruct  →  type(node) not in approved
          └── raises ValueError: "Non-approved construct type: ...NaughtyConstruct"
                  ↑
          deployment never reaches CloudFormation
```

Because approval is based on Python **type identity** (not a string), a construct
cannot lie about what it is — you must import the real class to be approved.

---

## Server-side enforcement with an SCP

The CDK-side check is a **client-side guardrail**: a sufficiently determined team
could bypass it by writing raw CloudFormation, using Terraform, or calling the AWS
CLI directly. A **Service Control Policy (SCP)** closes this gap — it runs inside
AWS on every API call, regardless of tooling.

### How BomAspect stamps the stack

When all constructs pass validation, `BomAspect` stamps the stack with
`xirokampi:validated = "true"`. CDK passes this as a request tag when it calls
`CreateStack` / `UpdateStack`.

### The SCP

Attach this policy to the OU that contains your Xirokampi data-product accounts:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyStackOpsWithoutXirokampiValidation",
      "Effect": "Deny",
      "Action": [
        "cloudformation:CreateStack",
        "cloudformation:UpdateStack"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestTag/xirokampi:validated": "true"
        }
      }
    }
  ]
}
```

### Two-layer defence

```
  Developer laptop / CI pipeline
  ─────────────────────────────────────────────────────────
  app.synth()
    BomAspect validates construct types        ← Layer 1: client-side
    All approved → stamps xirokampi:validated=true
    Raises if not approved → stops here
  cdk deploy
    calls cloudformation:UpdateStack
      with tag xirokampi:validated=true
  ─────────────────────────────────────────────────────────
           │
           ▼  (network boundary)
  ─────────────────────────────────────────────────────────
  AWS Organisation SCP evaluation              ← Layer 2: server-side
    aws:RequestTag/xirokampi:validated == "true"?
      yes → allow
      no  → Deny  (raw CFN, Terraform, CLI, console all blocked)
  ─────────────────────────────────────────────────────────
           │
           ▼
  CloudFormation executes the changeset
```

### Residual gap and stronger options

The SCP checks the tag **value**, not a cryptographic proof — a team that knows
the tag could add it manually to a raw template. For stronger guarantees:

- **Restrict stack creation to CI/CD** — limit `cloudformation:CreateStack` to a
  specific IAM role that only runs via a governed pipeline.
- **CloudFormation Guard Hook** — runs Guard rules *inside CloudFormation*,
  server-side, against the full template body. Cannot be bypassed by adding a tag.
- **AWS Config rules** — audit deployed templates post-hoc and raise findings for
  stacks that lack expected BOM metadata.

#### CloudFormation Guard Hook example

```python
from aws_cdk import aws_cloudformation as cfn

cfn.CfnGuardHook(self, "XirokampiGuardHook",
    alias="XirokampiBomValidation",
    rule_location=cfn.CfnGuardHook.S3LocationProperty(
        uri="s3://xirokampi-hooks/bom_check.guard",
    ),
    failure_mode="FAIL",
    target_operations=["STACK"],
)
```

---

## Where the BOM is visible

| Location | How to access | What you see |
|---|---|---|
| CloudFormation Template tab | Console → Stack → Template | Full BOM JSON under `Metadata` |
| CLI | `make bom` | Same JSON, live from deployed stack |
| Resource tags | Any AWS console, Cost Explorer, AWS Config | `xirokampi:construct = "FooConstruct@1.0.0"` on every resource |
| CloudFormation Resources list | Console → Stack → Resources | **Not shown** (CDK constructs ≠ CFN Modules) |

---

## What Org policies can and cannot check

SCPs evaluate **IAM condition keys on the API call** — request tags, principal
ARN, region. They have no access to the template body. The table below shows
what each enforcement layer can actually see:

| What you want to verify | SCP | Guard Hook | Config rule |
|---|---|---|---|
| `BomAspect` ran at all | ✓ (`xirokampi:validated` tag) | ✓ | ✓ |
| BOM is non-empty (`Count > 0`) | ✗ | ✓ | ✓ (post-deploy) |
| Constructs came from `xirokampi_utils` | ✗ | ✓ | ✓ (post-deploy) |
| The BOM wasn't hand-written | ✗ | ✗ | ✗ |

**The SCP only proves `BomAspect` ran — not which constructs it found.**
A stack with `BomAspect(approved=set())` passes the SCP (trivially zero
constructs to validate), stamps the tag, and deploys with no Xirokampi
constructs at all.

The only way to close that gap server-side without trusting the template is to
**restrict `cloudformation:CreateStack` to a governed CI/CD role**. The pipeline
then guarantees CDK + BomAspect ran correctly, and server-side checks become
belt-and-braces rather than the primary control.

---

## Auditing: who used which constructs (best effort)

Neither AWS Organizations nor CloudFormation have a built-in BOM registry.
The following are best-effort approaches using existing AWS tooling.

### For the Xirokampi Platform team

The `xirokampi:construct` tag is applied to **every AWS resource** created by a
Xirokampi construct. This is the most useful audit signal because it persists on
the resource even if the stack is updated or the BOM metadata changes.

**Tag Editor (console)** — cross-account, cross-region search:
```
AWS Console → Resource Groups & Tag Editor → Tag Editor
  Tag key:   xirokampi:construct
  Tag value: (leave blank to find all, or "FooConstruct@1.0.0" for a specific version)
  Regions:   all
  Resource types: all
```
This gives a flat list of every resource under Xirokampi management, grouped by
construct version. Useful for answering "which data products are still on
`FooConstruct@1.0.0` and need upgrading?"

**Per-stack BOM query** — requires access to each account:
```bash
# List all stacks with the validated tag in an account
aws cloudformation describe-stacks \
  --query "Stacks[?Tags[?Key=='xirokampi:validated'&&Value=='true']].StackName"

# Pull the full BOM from a specific stack
aws cloudformation get-template \
  --stack-name <StackName> \
  --query 'TemplateBody.Metadata.BOM' \
  --output json
```

**Cost Explorer** — filter costs by construct:
```
AWS Cost Explorer → Filter by Tag → xirokampi:construct
```
Shows spend attributable to each construct version across all data products.

### For the Org admin

The Org admin typically has read access across accounts via AWS Organizations
but does not control the Xirokampi platform.

**AWS Config Aggregator** — query tag compliance across all member accounts:
```sql
-- AWS Config Advanced Query (aggregator)
SELECT
  accountId, awsRegion, resourceId, resourceName,
  tags.value AS construct_version
WHERE
  resourceType = 'AWS::CloudFormation::Stack'
  AND tags.key = 'xirokampi:validated'
```
This shows which accounts have deployed validated stacks, but not the construct
breakdown — the BOM metadata is not queryable via Config.

**CloudTrail** — who deployed what and when:
```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateStack \
  --query 'Events[*].{Who:Username,Stack:CloudTrailEvent}' \
  --output table
```

### The honest picture

```
Org admin can see (without Xirokampi platform access):
  ✓  Which accounts have stacks tagged xirokampi:validated=true
  ✓  Which accounts have resources tagged xirokampi:construct=*
  ✓  Who deployed what, when (CloudTrail)
  ✗  Which specific construct versions are deployed where
  ✗  Whether BOM metadata is genuine vs hand-written

Xirokampi Platform team can see (with per-account access):
  ✓  Full BOM per stack via cloudformation:GetTemplate
  ✓  All resources by construct+version via Tag Editor
  ✓  Cost per construct version via Cost Explorer
  ✗  Whether the BOM was generated by BomAspect or hand-written
```

For a richer audit view, the Platform team can run a cross-account Lambda that
iterates every account → every stack with `xirokampi:validated=true` → calls
`GetTemplate` → aggregates `Metadata.BOM` into a central store (DynamoDB, S3,
or a dashboard). This is outside the scope of this spike but the data is all
there.

---

## Authoritative AWS guidance

The approach in this spike follows the official
[AWS CDK Best Practices](https://docs.aws.amazon.com/cdk/v2/guide/best-practices.html)
guide (retrieved 2026-03-25):

> **"Constructs aren't enough for compliance"**
> This pattern is useful for surfacing security guidance early in the software
> development lifecycle, **but don't rely on it as the sole means of enforcement**.
> Instead, use AWS features such as **service control policies** and **permission
> boundaries** to enforce your security guardrails at the organization level.
> Use **[Aspects](https://docs.aws.amazon.com/cdk/v2/guide/aspects.html)** and the
> AWS CDK or tools like **[CloudFormation Guard](https://github.com/aws-cloudformation/cloudformation-guard)**
> to make assertions about the security properties of infrastructure elements
> before deployment.

This spike is `BomAspect` (CDK Aspect, client-side) + SCP (org-level) +
optionally `CfnGuardHook` (server-side) — exactly the recommended stack.

### Tag key naming

**`xirokampi:construct` is a Xirokampi-specific convention, not an AWS standard.**

The [AWS Tagging Best Practices whitepaper](https://docs.aws.amazon.com/whitepapers/latest/tagging-best-practices/tagging-best-practices.html)
recommends a consistent tagging strategy but leaves key naming to the organisation.
The `:` namespace separator (`xirokampi:construct`) is a common convention for
platform-owned tags.

### CDK Blueprints — a different feature

[CDK Blueprints](https://docs.aws.amazon.com/cdk/v2/guide/blueprints.html)
(aws-cdk-lib v2.196.0+) use *property injection* to apply defaults to L2 constructs
(e.g. force S3 encryption, standardise Lambda runtimes). They are **not** a BOM or
enforcement mechanism — the AWS docs say: *"Blueprints are not a compliance
enforcement mechanism."*

---

## Limitations

### BOM reflects last resource change, not latest library version

CloudFormation changesets only track **resource** changes. Template-level
`Metadata` (where the BOM lives) is invisible to the changeset engine — if a
library version bumps but no resource properties change, CloudFormation reports
"no changes" and skips the deploy. The deployed BOM then still shows the
previous version.

This is actually useful information: **the BOM version is the version that last
had a material impact on the deployed resources**, not merely the version that
was installed at the time of the last `cdk deploy`. A bump from
`FooConstruct@1.0.0` to `1.0.1` that only fixes a docstring genuinely did not
change anything in the account — the BOM accurately reflects that `1.0.0` is
what shaped the infrastructure.

**`BomAspect` works around this** by also writing construct versions into the
`xirokampi:bom` stack tag (e.g. `FooConstruct@1.0.0,BarConstruct@1.0.0`).
Stack tags live in the CloudFormation changeset — not just the template — so
any version bump changes the tag, CloudFormation detects a real change, and the
deploy proceeds. The deployed BOM metadata then stays accurate.

The corollary: if you need the BOM to reflect the *currently installed* version
regardless of resource impact, read from the local synthesis output instead of
the deployed stack:

```bash
# Always current — reflects the code on disk right now
make bom          # reads cdk.out/ after re-synth

# Historical — reflects the last deploy that changed a resource
aws cloudformation get-template \
  --stack-name AwsCdkBomStack \
  --query 'TemplateBody.Metadata.BOM' \
  --output json
```

### BomAspect only detects XirokampiConstruct subclasses

Standard
L2/L3 constructs from `aws-cdk-lib` or third-party libraries are invisible to it:

```
Stack
 ├── FooConstruct (XirokampiConstruct)  ✓  detected, validated
 ├── BarConstruct (XirokampiConstruct)  ✓  detected, validated
 ├── s3.Bucket (aws-cdk-lib L2)         ✗  invisible to BomAspect
 └── Widget (constructs.dev)            ✗  invisible to BomAspect
```

To cover arbitrary third-party constructs, the Aspect can reverse-map any Python
type to its installed package via `importlib.metadata.packages_distributions()` —
at the cost of more noise from internal CDK helpers.

---

## Repository structure

```
aws-cdk-bom/
├── Makefile
├── pyproject.toml                          ← uv workspace root
├── app.py                                  ← CDK app entry point
├── cdk.json
├── packages/
│   ├── xirokampi-constructs-base/          ← shared XirokampiConstruct base class
│   │   ├── pyproject.toml  (v0.1.0)
│   │   └── xirokampi_constructs_base/__init__.py
│   └── xirokampi-utils/                    ← FooConstruct + BarConstruct (shared version)
│       ├── pyproject.toml  (v1.0.0)
│       └── xirokampi_utils/__init__.py
├── aws_cdk_bom/
│   ├── aspects/
│   │   └── bom_aspect.py                  ← BomAspect: validates + records BOM
│   └── aws_cdk_bom_stack.py               ← stack wiring
└── tests/unit/
    └── test_aws_cdk_bom_stack.py
```

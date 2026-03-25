# aws-cdk-bom — CDK Bill of Materials Spike

This spike explores how to verify that a deployed CloudFormation stack was built
from **approved, versioned enterprise constructs** — a Bill of Materials (BOM).

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

Each enterprise construct is its own Python package. The version lives in exactly
one place — `pyproject.toml` — and propagates automatically at import time:

```
packages/enterprise-foo-construct/pyproject.toml
  [project]
  name    = "enterprise-foo-construct"
  version = "1.0.0"            ← single source of truth
        │
        │  uv sync  (installs the package into .venv)
        ▼
  importlib.metadata.version("enterprise-foo-construct")  → "1.0.0"
        │
        ▼
  class FooConstruct(EnterpriseConstruct):
      CONSTRUCT_VERSION = version("enterprise-foo-construct")   ← set at import time
        │
        ├──► Tags.of(self).add("enterprise:construct-version", "1.0.0")
        │         every CFN resource created by Foo carries this tag
        │
        ├──► param.node.default_child.cfn_options.metadata
        │         = {"Enterprise": {"construct-version": "1.0.0"}}
        │         written into the CFN resource's Metadata block
        │
        └──► BomAspect.visit(stack)
                  walks node.node.find_all() at synth time
                  finds every EnterpriseConstruct in the tree
                        │
                        ▼
              stack.template_options.metadata = {
                  "BOM": {
                      "Constructs": [
                          {"name": "FooConstruct", "version": "1.0.0", ...},
                          {"name": "BarConstruct", "version": "2.1.0", ...}
                      ],
                      "ApprovedList": ["FooConstruct@1.0.0", ...],
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
1. packages/enterprise-bar-construct/pyproject.toml:  version = "2.1.0" → "2.1.1"
2. make install          # uv rebuilds and reinstalls the package
3. BarConstruct.CONSTRUCT_VERSION is now "2.1.1" (set at import time)
4. APPROVED_CONSTRUCTS in the stack auto-derives from the class attribute,
   so the approved list updates too
5. make deploy           # BOM in the live template shows "2.1.1"
```

### BOM enforcement (validation)

`BomAspect` is initialised with a set of approved class objects. If any construct
in the stack is not in that set, synthesis raises immediately — before any AWS API
call is made. Because approval is based on Python type identity rather than a
string, a construct cannot lie about what it is (see *Spoof resistance* below).

```
BomAspect(approved={FooConstruct, BarConstruct})

  app.synth()
    └── BomAspect.visit(Stack)
          ├── finds NaughtyConstruct  →  type(node) not in approved
          └── raises ValueError: "Non-approved construct type: ...NaughtyConstruct"
                  ↑
          deployment never reaches CloudFormation
```

---

## Server-side enforcement with an SCP

The CDK-side check above is a **client-side guardrail**: a sufficiently determined
team could bypass it by writing raw CloudFormation, using Terraform, or calling the
AWS CLI directly — none of which run `BomAspect`.

A **Service Control Policy (SCP)** applied at the AWS Organisation level closes
this gap. It runs inside AWS, on every API call, regardless of the tooling used.

### How BomAspect stamps the stack

When all constructs pass validation, `BomAspect` adds a `bom:validated = "true"`
tag to the CloudFormation **stack** resource (not just the resources inside it).
CDK passes this as a request tag when it calls `CreateStack` / `UpdateStack`.

```python
# aws_cdk_bom/aspects/bom_aspect.py (simplified)

# validation loop raises if any construct is unapproved …

# … only reached if everything passed:
cdk.Tags.of(stack_node).add("bom:validated", "true")
```

### The SCP

Attach this policy to the OU that contains your data-product accounts:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyStackOpsWithoutBomTag",
      "Effect": "Deny",
      "Action": [
        "cloudformation:CreateStack",
        "cloudformation:UpdateStack"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestTag/bom:validated": "true"
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
    BomAspect validates construct types       ← Layer 1: client-side
    All approved → stamps bom:validated=true
    Raises if not approved → stops here
  cdk deploy
    calls cloudformation:UpdateStack
      with tag bom:validated=true
  ─────────────────────────────────────────────────────────
           │
           ▼  (network boundary)
  ─────────────────────────────────────────────────────────
  AWS Organisation SCP evaluation             ← Layer 2: server-side
    aws:RequestTag/bom:validated == "true"?
      yes → allow
      no  → Deny  (raw CFN, Terraform, CLI, console all blocked)
  ─────────────────────────────────────────────────────────
           │
           ▼
  CloudFormation executes the changeset
```

### Residual gap

The SCP checks the **tag value**, not a cryptographic proof. A team that knows the
magic tag string could include it manually in a raw template:

```bash
aws cloudformation create-stack \
  --stack-name cheat \
  --template-body file://raw.yaml \
  --tags Key=bom:validated,Value=true   # ← manually added, bypasses CDK entirely
```

The tag alone therefore provides audit trail and raises the bar for accidental
non-compliance, but is not tamper-proof. For stronger guarantees:

- **Restrict who can create stacks** — limit `cloudformation:CreateStack` to a
  specific CI/CD IAM role that only runs via a governed pipeline. The SCP then
  denies the action for all other principals entirely, making the tag condition
  moot for human users.
- **CloudFormation Guard Hooks** — a `CfnGuardHook` runs Guard rules *inside
  CloudFormation*, between change-set creation and resource deployment. Unlike
  the tag SCP it can inspect the full template structure, including the `Metadata`
  block we write. A Guard rule can assert that `BOM.Count > 0` and that every
  entry in `BOM.Constructs` has a recognised `module` value — this runs
  server-side regardless of tooling and cannot be bypassed by adding a tag.
- **Use AWS Config rules** — a custom Lambda-backed Config rule can audit deployed
  templates post-hoc and raise findings for stacks that lack expected BOM metadata.
- **Sign the BOM** — include a HMAC of the approved construct list (keyed to a
  secret stored in Secrets Manager) as a second tag. The pipeline generates the
  HMAC; a Lambda-backed Config rule validates the signature.

### CloudFormation Guard Hook (strongest server-side option)

A Guard Hook is a CloudFormation Hook registered in the account that runs a
`.guard` policy file against every change set before execution:

```
# bom_check.guard  (CloudFormation Guard rule)

# The stack template must contain a BOM metadata block
let bom = Resources.*[ Type == 'AWS::CloudFormation::Stack' ].Metadata.BOM
             default []

rule BOM_MUST_EXIST {
    %bom not empty
        <<BOM metadata is missing — stack was not deployed via BomAspect>>
}

rule BOM_MUST_HAVE_CONSTRUCTS when BOM_MUST_EXIST {
    %bom[*].Count >= 1
        <<BOM is empty — no approved constructs found>>
}
```

Registered via `CfnGuardHook` (CDK construct, aws-cdk-lib v2.x):

```python
from aws_cdk import aws_cloudformation as cfn

cfn.CfnGuardHook(self, "BomGuardHook",
    alias="BomValidation",
    rule_location=cfn.CfnGuardHook.S3LocationProperty(
        uri="s3://my-hooks-bucket/bom_check.guard",
    ),
    failure_mode="FAIL",
    target_operations=["STACK"],
)
```

This runs server-side, inspects the actual template body, and blocks the
changeset execution — not just the API call. It cannot be bypassed by tags or
by calling the CloudFormation API directly.

---

## Where the BOM is visible

| Location | How to access | What you see |
|---|---|---|
| CloudFormation Template tab | Console → Stack → Template | Full BOM JSON under `Metadata` |
| CLI | `make bom` | Same JSON, live from deployed stack |
| Per-resource Metadata | Template JSON per resource | `Enterprise.construct-name/version` |
| Resource Tags | SSM / any AWS console, Cost Explorer | `enterprise:construct-name/version` tags |
| CloudFormation Resources list | Console → Stack → Resources | **Not shown** (see Module column below) |

### The Module column

The **Module** column in the CloudFormation Resources list is reserved for
[CloudFormation Modules](https://docs.aws.amazon.com/cloudformation-cli/latest/userguide/modules.html)
— a separate, CloudFormation-native mechanism. Modules are authored in CFN
JSON/YAML and published to the CloudFormation Registry as types like
`MyCompany::Constructs::Foo::MODULE`. Resources created by a registered Module
show its name and version in that column.

CDK constructs are not CloudFormation Modules, so the column shows `-`. If
per-resource visibility in the Resources list is a hard requirement, CloudFormation
Modules are the native path — but they are authored outside CDK.

---

## Limitations and scaling

> The approach in this spike is consistent with
> [AWS CDK best practices](https://docs.aws.amazon.com/cdk/v2/guide/best-practices.html):
> *"Don't rely on wrapper constructs as the sole means of enforcement. Use SCPs and
> permission boundaries to enforce guardrails at the organisation level. Use Aspects
> or CloudFormation Guard to make assertions about infrastructure before deployment."*
> Our `BomAspect` is a **read-only Aspect** (the recommended CDK pattern for auditing
> and compliance logging) combined with server-side SCP/Guard enforcement.

### This spike only detects constructs you control

`BomAspect` finds nodes that inherit from `EnterpriseConstruct`. Third-party L2/L3
constructs — from `aws-cdk-lib` or [constructs.dev](https://constructs.dev) — will
not be detected because they do not subclass `EnterpriseConstruct` and do not set
`CONSTRUCT_NAME` / `CONSTRUCT_VERSION`.

```
Stack
 ├── FooConstruct (EnterpriseConstruct)  ✓  detected
 ├── BarConstruct (EnterpriseConstruct)  ✓  detected
 ├── s3.Bucket (L2, aws-cdk-lib)         ✗  invisible to BomAspect
 └── some_lib.Widget (constructs.dev)    ✗  invisible to BomAspect
```

### A more automatic approach: inspect the package graph

Rather than requiring construct authors to cooperate, the Aspect can introspect
the Python type of any node and reverse-map it to its installed package:

```python
import importlib.metadata

def package_of(node) -> tuple[str, str] | None:
    """Return (package_name, version) for any construct node, or None."""
    module_name = type(node).__module__          # e.g. "aws_cdk.aws_s3"
    top_level = module_name.split(".")[0]        # e.g. "aws_cdk"

    # Map top-level module → distribution package name
    pkgs = importlib.metadata.packages_distributions()
    dist_names = pkgs.get(top_level, [])
    if not dist_names:
        return None

    dist = dist_names[0]                         # e.g. "aws-cdk-lib"
    return dist, importlib.metadata.version(dist)
```

With this, a `PackageBomAspect` could walk the entire tree and emit a BOM of
every distinct package used — `aws-cdk-lib@2.x`, `enterprise-foo-construct@1.0.0`,
`some-constructs@3.2.1` — without any changes to the construct authors.

The trade-off is noise: you get every internal CDK L1 construct and helper, not
just the top-level patterns you care about. Filtering by package prefix
(`enterprise-*`) recovers the signal.

### CDK Blueprints (v2.196.0+)

[CDK Blueprints](https://docs.aws.amazon.com/cdk/v2/guide/blueprints.html) are a
newer mechanism for distributing default L2 configurations across an organisation
via *property injection*. A Blueprint can ensure every `s3.Bucket` has encryption
enabled, or every `lambda.Function` uses a specific runtime, without wrapping the
construct.

Blueprints solve a different problem to this spike — they set *defaults*, not
*allowlists*. The docs explicitly note: *"Blueprints are not a compliance
enforcement mechanism... For strict compliance enforcement, consider using
CloudFormation Guard, SCPs, or CDK Aspects in addition to Blueprints."*

### CDK's own Analytics metadata

CDK already writes a compressed `Analytics` value into the `CDKMetadata` resource
on every stack (visible in the Resources list). This encodes construct class usage
for CDK telemetry. It is not designed for human consumption or enforcement, but
the same data is available if you walk `node.node.find_all()` and inspect
`type(node).__jsii_type__` (the fully-qualified JSII type name).

---

## Repository structure

```
aws-cdk-bom/
├── Makefile
├── pyproject.toml                        ← uv workspace root
├── app.py                                ← CDK app entry point
├── cdk.json
├── packages/
│   ├── enterprise-constructs-base/       ← shared base class
│   │   ├── pyproject.toml  (v0.1.0)
│   │   └── enterprise_constructs_base/__init__.py
│   ├── enterprise-foo-construct/         ← versioned enterprise construct
│   │   ├── pyproject.toml  (v1.0.0)
│   │   └── enterprise_foo_construct/__init__.py
│   └── enterprise-bar-construct/         ← versioned enterprise construct
│       ├── pyproject.toml  (v2.1.0)
│       └── enterprise_bar_construct/__init__.py
├── aws_cdk_bom/
│   ├── aspects/
│   │   └── bom_aspect.py               ← BomAspect: collects + validates BOM
│   └── aws_cdk_bom_stack.py            ← stack wiring
└── tests/unit/
    └── test_aws_cdk_bom_stack.py
```

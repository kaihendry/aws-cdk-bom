import jsii
import aws_cdk as cdk
from constructs import IConstruct
from xirokampi_constructs_base import XirokampiConstruct

# This tag is added to the CloudFormation stack when BOM validation passes.
# An SCP can deny cloudformation:CreateStack / UpdateStack unless this tag
# is present, blocking any deployment that bypassed CDK + BomAspect entirely.
BOM_VALIDATED_TAG = "xirokampi:validated"


@jsii.implements(cdk.IAspect)
class BomAspect:
    def __init__(self, approved: set[type]) -> None:
        # Approved is a set of actual class objects, not strings.
        # type(node) is SomeClass cannot be faked without importing the real class.
        self._approved = approved
        self._stack_registered = False

    def visit(self, node: IConstruct) -> None:
        if not (isinstance(node, cdk.Stack) and not self._stack_registered):
            return

        self._stack_registered = True

        # The construct tree is fully built before synth runs, so find_all()
        # gives us the complete picture right now — no lazy evaluation needed.
        enterprise_nodes = [
            child for child in node.node.find_all()
            if isinstance(child, XirokampiConstruct)
        ]

        # Validate every enterprise construct against the approved type set.
        # type() is used rather than isinstance() so that a subclass of an
        # approved construct is not itself considered approved.
        for child in enterprise_nodes:
            if type(child) not in self._approved:
                fqn = f"{type(child).__module__}.{type(child).__qualname__}"
                raise ValueError(
                    f"Non-approved construct type: {fqn}. "
                    f"Approved: {sorted(f'{c.__module__}.{c.__name__}' for c in self._approved)}"
                )

        # All constructs approved — stamp the stack with the validation tag.
        # An SCP at the AWS Organisation level can then deny CreateStack /
        # UpdateStack unless aws:RequestTag/bom:validated equals "true".
        # Use node.tags.set_tag() rather than Tags.of().add() to avoid the
        # Aspect priority conflict (CDK rejects adding a Tag Aspect at priority
        # 200 after BomAspect has already run at priority 500).
        node.tags.set_tag(BOM_VALIDATED_TAG, "true")

        # Write the BOM summary into the stack's CloudFormation template Metadata.
        bom_entries = [
            {
                "blueprint": child.construct_id,           # "FooConstruct@1.0.0"
                "module":    type(child).__module__,
                "path":      child.node.path,
            }
            for child in enterprise_nodes
        ]
        node.template_options.metadata = {
            "BOM": {
                "GeneratedAt":  "synth-time",
                "ApprovedTypes": [
                    f"{cls.__module__}.{cls.__name__}" for cls in self._approved
                ],
                "Constructs":   bom_entries,
                "Count":        len(bom_entries),
            }
        }

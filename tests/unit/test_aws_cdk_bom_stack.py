import pytest
import aws_cdk as cdk
from aws_cdk import assertions
from aws_cdk_bom.aws_cdk_bom_stack import AwsCdkBomStack
from aws_cdk_bom.aspects import BomAspect
from xirokampi_constructs_base import XirokampiConstruct
from xirokampi_utils import FooConstruct, BarConstruct


def make_template() -> assertions.Template:
    app = cdk.App()
    stack = AwsCdkBomStack(app, "TestStack")
    app.synth()
    return assertions.Template.from_stack(stack)


def test_bom_metadata_exists():
    bom = make_template().to_json()["Metadata"]["BOM"]
    assert bom["Count"] == 2
    assert bom["GeneratedAt"] == "synth-time"


def test_foo_in_bom():
    constructs = make_template().to_json()["Metadata"]["BOM"]["Constructs"]
    assert any(c["blueprint"].startswith("FooConstruct@") for c in constructs)


def test_bar_in_bom():
    constructs = make_template().to_json()["Metadata"]["BOM"]["Constructs"]
    assert any(c["blueprint"].startswith("BarConstruct@") for c in constructs)


def test_bom_records_module_path():
    """The BOM records the fully-qualified module, not just the class name string."""
    constructs = make_template().to_json()["Metadata"]["BOM"]["Constructs"]
    foo = next(c for c in constructs if c["blueprint"].startswith("FooConstruct@"))
    assert foo["module"] == "xirokampi_utils"


def test_two_ssm_parameters():
    make_template().resource_count_is("AWS::SSM::Parameter", 2)


def test_xirokampi_construct_tag_on_resources():
    t = make_template()
    t.has_resource_properties("AWS::SSM::Parameter", {
        "Tags": assertions.Match.object_like({"xirokampi:construct": assertions.Match.string_like_regexp("^FooConstruct@")})
    })
    t.has_resource_properties("AWS::SSM::Parameter", {
        "Tags": assertions.Match.object_like({"xirokampi:construct": assertions.Match.string_like_regexp("^BarConstruct@")})
    })


def test_unapproved_construct_raises():
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    FooConstruct(stack, "Foo")
    cdk.Aspects.of(stack).add(BomAspect(approved=set()))
    # ValueError is wrapped by JSII as RuntimeError on the way back from the JS kernel
    with pytest.raises(Exception, match="Non-approved construct type"):
        app.synth()


def test_spoof_attempt_is_caught():
    """A construct that inherits from XirokampiConstruct is caught because
    BomAspect checks type identity, not the blueprint string."""

    class NaughtyConstruct(XirokampiConstruct):
        # blueprint_id will be "NaughtyConstruct@unknown" — derived automatically
        def __init__(self, scope, construct_id, **kwargs):
            super().__init__(scope, construct_id, **kwargs)

    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    NaughtyConstruct(stack, "Naughty")
    # FooConstruct is approved, but NaughtyConstruct is NOT FooConstruct
    cdk.Aspects.of(stack).add(BomAspect(approved={FooConstruct}))

    with pytest.raises(Exception, match="NaughtyConstruct"):
        app.synth()

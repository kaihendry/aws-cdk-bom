import pytest
import aws_cdk as cdk
from aws_cdk import assertions
from aws_cdk_bom.aws_cdk_bom_stack import AwsCdkBomStack
from aws_cdk_bom.aspects import BomAspect
from enterprise_constructs_base import EnterpriseConstruct
from enterprise_foo_construct import FooConstruct
from enterprise_bar_construct import BarConstruct


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
    assert any(
        c["name"] == "FooConstruct" and c["version"] == FooConstruct.CONSTRUCT_VERSION
        for c in constructs
    )


def test_bar_in_bom():
    constructs = make_template().to_json()["Metadata"]["BOM"]["Constructs"]
    assert any(
        c["name"] == "BarConstruct" and c["version"] == BarConstruct.CONSTRUCT_VERSION
        for c in constructs
    )


def test_bom_records_module_path():
    """The BOM records the fully-qualified module, not just the class name string."""
    constructs = make_template().to_json()["Metadata"]["BOM"]["Constructs"]
    foo = next(c for c in constructs if c["name"] == "FooConstruct")
    assert foo["module"] == "enterprise_foo_construct"


def test_two_ssm_parameters():
    make_template().resource_count_is("AWS::SSM::Parameter", 2)


def test_enterprise_tags_on_resources():
    t = make_template()
    t.has_resource_properties("AWS::SSM::Parameter", {
        "Tags": assertions.Match.object_like({"enterprise:construct-name": "FooConstruct"})
    })
    t.has_resource_properties("AWS::SSM::Parameter", {
        "Tags": assertions.Match.object_like({"enterprise:construct-name": "BarConstruct"})
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
    """A construct that lies about its CONSTRUCT_NAME/VERSION is caught because
    BomAspect checks type identity, not the name/version strings."""

    class NaughtyConstruct(EnterpriseConstruct):
        CONSTRUCT_NAME    = "FooConstruct"  # lying
        CONSTRUCT_VERSION = "1.0.0"         # lying

        def __init__(self, scope, construct_id, **kwargs):
            super().__init__(scope, construct_id, **kwargs)

    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    NaughtyConstruct(stack, "Naughty")
    # FooConstruct is approved, but NaughtyConstruct is NOT FooConstruct
    cdk.Aspects.of(stack).add(BomAspect(approved={FooConstruct}))

    with pytest.raises(Exception, match="NaughtyConstruct"):
        app.synth()

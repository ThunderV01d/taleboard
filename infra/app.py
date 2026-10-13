import aws_cdk as cdk

from taleboard_stack import TaleboardStack

app = cdk.App()
TaleboardStack(app, "TaleboardStack", env=cdk.Environment(account="245166789333", region="eu-west-2"))
app.synth()
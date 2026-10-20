import aws_cdk as cdk

from taleboard_stack import TaleboardStack

app = cdk.App()
env = cdk.Environment(account="245166789333", region="eu-west-2")
TaleboardStack(app, "TaleboardStack", env=env) # Live 0.1.0 release
TaleboardStack(app, "TaleboardStack-dev",env=env) # 0.2.0 development
app.synth()
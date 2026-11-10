import aws_cdk as cdk

from budget_stack import BudgetStack
from taleboard_stack import TaleboardStack

app = cdk.App()
env = cdk.Environment(account="245166789333", region="eu-west-2")
TaleboardStack(app, "TaleboardStack", env=env) # Live 0.1.0 release
TaleboardStack(app, "TaleboardStack-dev",env=env) # 0.2.0 development
# The whole account's (both stacks') monthly spend alerts -- only once there's an address to send them to
budget_email = app.node.try_get_context("budgetEmail") or app.node.try_get_context("alarmEmail")
if budget_email:
    BudgetStack(app, "TaleboardBudget", email=budget_email, env=env)
app.synth()
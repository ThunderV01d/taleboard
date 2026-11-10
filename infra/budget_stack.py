"""
CDK stack for the account's monthly AWS budget: an email when spending passes set shares of it.

A budget covers the whole account -- both TaleBoard stacks -- so it's a stack of its own, deployed once. It covers AWS
charges only (Bedrock included); Together AI bills separately.

Attributes:
    MONTHLY_LIMIT_USD: float - The monthly budget, in US dollars (AWS budgets are in USD).
    ACTUAL_ALERTS: list[int] - Emails go out when actual spending passes each of these percentages of it.
    FORECAST_ALERT: int - And when the month's forecast passes this percentage.
"""
from aws_cdk import Stack
from aws_cdk import aws_budgets as budgets
from constructs import Construct

MONTHLY_LIMIT_USD = 6.0
ACTUAL_ALERTS = [50, 80, 100]
FORECAST_ALERT = 100


class BudgetStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, email: str, **kwargs) -> None:
        """
        Arguments:
            email: str - Where the alerts go (budgetEmail, or alarmEmail, in infra/cdk.json).
        """
        super().__init__(scope, construct_id, **kwargs)
        subscribers = [budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=email)]

        def alert(kind: str, percent: int) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    notification_type=kind,
                    comparison_operator="GREATER_THAN",
                    threshold=percent,
                    threshold_type="PERCENTAGE",
                ),
                subscribers=subscribers,
            )

        budgets.CfnBudget(
            self, "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="taleboard-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=MONTHLY_LIMIT_USD, unit="USD"),
            ),
            notifications_with_subscribers=[
                *(alert("ACTUAL", percent) for percent in ACTUAL_ALERTS),
                alert("FORECASTED", FORECAST_ALERT),
            ],
        )

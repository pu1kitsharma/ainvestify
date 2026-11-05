#!/bin/bash
# Spending guard for the GPU instance: alerts, a monthly budget and an hours limit that stops the machine.
# Usage: ALERT_EMAIL=you@example.com bash deploy/aws/setup_guard.sh
# Safe to run again. Creates nothing that bills by the hour.
set -euo pipefail
AWS=${AWS:-aws}
export MSYS_NO_PATHCONV=1
REGION=ap-south-1
HERE=$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))
WORK=$(mktemp -d .deal-gpu-guard-XXXX)
trap 'rm -rf "$WORK"' EXIT
ACCOUNT=$("$AWS" sts get-caller-identity --query Account --output text | tr -d '\r')
BUDGET_USD=${BUDGET_USD:-150}          # Rs 15,000 at a planning rate of Rs 100 per dollar, tax included
MAX_MONTH_HOURS=${MAX_MONTH_HOURS:-32}
MAX_SESSION_HOURS=${MAX_SESSION_HOURS:-6}

TOPIC=$("$AWS" sns create-topic --region $REGION --name deal-gpu-alerts --query TopicArn --output text | tr -d '\r')
"$AWS" sns subscribe --region $REGION --topic-arn "$TOPIC" --protocol email --notification-endpoint "$ALERT_EMAIL" >/dev/null

cat > "$WORK/trust.json" <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
cat > "$WORK/policy.json" <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"ec2:DescribeInstances","Resource":"*"},
 {"Effect":"Allow","Action":"ec2:StopInstances","Resource":"arn:aws:ec2:$REGION:$ACCOUNT:instance/*","Condition":{"StringEquals":{"aws:ResourceTag/Project":"deal-gpu"}}},
 {"Effect":"Allow","Action":["ssm:GetParameter","ssm:PutParameter"],"Resource":"arn:aws:ssm:$REGION:$ACCOUNT:parameter/deal-gpu/*"},
 {"Effect":"Allow","Action":"sns:Publish","Resource":"$TOPIC"},
 {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],"Resource":"arn:aws:logs:$REGION:$ACCOUNT:*"}]}
EOF
"$AWS" iam get-role --role-name deal-gpu-guard >/dev/null 2>&1 || \
  "$AWS" iam create-role --role-name deal-gpu-guard --assume-role-policy-document "file://$WORK/trust.json" >/dev/null
"$AWS" iam put-role-policy --role-name deal-gpu-guard --policy-name deal-gpu-guard --policy-document "file://$WORK/policy.json"
ROLE="arn:aws:iam::$ACCOUNT:role/deal-gpu-guard"

python - "$HERE/gpu_guard.py" "$WORK/guard.zip" <<'EOF'
import sys, zipfile
with zipfile.ZipFile(sys.argv[2], 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.write(sys.argv[1], 'gpu_guard.py')
EOF
ENVIRONMENT="Variables={TOPIC_ARN=$TOPIC,MAX_MONTH_HOURS=$MAX_MONTH_HOURS,MAX_SESSION_HOURS=$MAX_SESSION_HOURS,TICK_MINUTES=5}"
if "$AWS" lambda get-function --region $REGION --function-name deal-gpu-guard >/dev/null 2>&1; then
  "$AWS" lambda update-function-code --region $REGION --function-name deal-gpu-guard --zip-file "fileb://$WORK/guard.zip" >/dev/null
  "$AWS" lambda wait function-updated --region $REGION --function-name deal-gpu-guard
  "$AWS" lambda update-function-configuration --region $REGION --function-name deal-gpu-guard --environment "$ENVIRONMENT" >/dev/null
else
  for attempt in 1 2 3 4 5 6; do   # a new role takes a few seconds to reach Lambda
    "$AWS" lambda create-function --region $REGION --function-name deal-gpu-guard --runtime python3.12 --handler gpu_guard.handler \
      --role "$ROLE" --timeout 30 --zip-file "fileb://$WORK/guard.zip" --environment "$ENVIRONMENT" >/dev/null 2>&1 && break
    sleep 10
  done
fi
"$AWS" lambda wait function-active-v2 --region $REGION --function-name deal-gpu-guard
FUNCTION=$("$AWS" lambda get-function --region $REGION --function-name deal-gpu-guard --query Configuration.FunctionArn --output text | tr -d '\r')
RULE=$("$AWS" events put-rule --region $REGION --name deal-gpu-guard --schedule-expression 'rate(5 minutes)' --state ENABLED --query RuleArn --output text | tr -d '\r')
"$AWS" lambda add-permission --region $REGION --function-name deal-gpu-guard --statement-id events --action lambda:InvokeFunction \
  --principal events.amazonaws.com --source-arn "$RULE" >/dev/null 2>&1 || true
"$AWS" events put-targets --region $REGION --rule deal-gpu-guard --targets "Id=guard,Arn=$FUNCTION" >/dev/null
# If the guard itself breaks, say so: a silent guard is the failure that costs money.
"$AWS" cloudwatch put-metric-alarm --region $REGION --alarm-name deal-gpu-guard-failing --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=deal-gpu-guard --statistic Sum --period 900 --evaluation-periods 1 --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold --treat-missing-data notBreaching --alarm-actions "$TOPIC"

cat > "$WORK/budget.json" <<EOF
{"BudgetName":"DealGpuMonthlyCap","BudgetLimit":{"Amount":"$BUDGET_USD","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}
EOF
python - "$WORK/notes.json" "$ALERT_EMAIL" <<'EOF'
import json, sys
alerts = [('ACTUAL', 50), ('ACTUAL', 80), ('ACTUAL', 100), ('FORECASTED', 100)]
json.dump([{'Notification': {'NotificationType': kind, 'ComparisonOperator': 'GREATER_THAN', 'Threshold': level, 'ThresholdType': 'PERCENTAGE'},
            'Subscribers': [{'SubscriptionType': 'EMAIL', 'Address': sys.argv[2]}]} for kind, level in alerts], open(sys.argv[1], 'w'))
EOF
"$AWS" budgets describe-budget --account-id "$ACCOUNT" --budget-name DealGpuMonthlyCap >/dev/null 2>&1 || \
  "$AWS" budgets create-budget --account-id "$ACCOUNT" --budget "file://$WORK/budget.json" --notifications-with-subscribers "file://$WORK/notes.json"
echo "guard ready: $MAX_MONTH_HOURS hours a month, $MAX_SESSION_HOURS hours a session, budget USD $BUDGET_USD"

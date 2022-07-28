import boto3
import os

sns = boto3.client('sns')

def lambda_handler(event, context):
    print(event)
    schema_name = event['repository']
    schema_name = schema_name[schema_name.rfind("/")+1:]
    schema_name = schema_name.replace("schema_", "")
    
    if event['build-status'] == 'SUCCEEDED':
        message = '''New version of schema '{0}' is available!'''.format(schema_name)
        print(message)
        response = sns.publish(
                    TopicArn=os.environ["SNSTopicArn"],
                    Message=message,
                    Subject='New Schema version available'
                )
        print("Message published to SNS topic")
    return
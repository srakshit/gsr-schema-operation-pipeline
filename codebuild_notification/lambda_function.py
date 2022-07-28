def lambda_handler(event, context):
    print(event)
    schema_name = event['repository']
    schema_name = schema_name[schema_name.rfind("/")+1:]
    schema_name = schema_name.replace("schema_", "")
    
    if event['build-status'] == 'SUCCEEDED':
        print("New version of schema '"+schema_name+"' is available!")
    
    return
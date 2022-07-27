from fileinput import filename
import os
import boto3
import yaml
import json
import re
from botocore.exceptions import ClientError

# Module level variables initialization
CODE_BUILD_PROJECT = os.getenv('CODE_BUILD_PROJECT')
AVRO_FILE_PATH = os.getenv('AVRO_FILE_PATH')
MANIFEST_FILE_PATH = os.getenv('MANIFEST_FILE_PATH')

codecommit = boto3.client('codecommit')
cb = boto3.client('codebuild')
gsr = boto3.client('glue')


def getLastCommitLog(repository, commitId):
    response = codecommit.get_commit(
        repositoryName=repository,
        commitId=commitId
    )
    return response['commit']


def getFileDifferences(repository_name, lastCommitID, previousCommitID):
    response = None

    if previousCommitID != None:
        response = codecommit.get_differences(
            repositoryName=repository_name,
            beforeCommitSpecifier=previousCommitID,
            afterCommitSpecifier=lastCommitID
        )
    else:
        # The case of getting initial commit (Without beforeCommitSpecifier)
        response = codecommit.get_differences(
            repositoryName=repository_name,
            afterCommitSpecifier=lastCommitID
        )

    differences = []

    if response == None:
        return differences

    while "nextToken" in response:
        response = codecommit.get_differences(
            repositoryName=repository_name,
            beforeCommitSpecifier=previousCommitID,
            afterCommitSpecifier=lastCommitID,
            nextToken=response["nextToken"]
        )
        differences += response.get("differences", [])
    else:
        differences += response["differences"]

    return differences


def getLastCommitID(repository, branch="master"):
    response = codecommit.get_branch(
        repositoryName=repository,
        branchName=branch
    )
    commitId = response['branch']['commitId']
    return commitId


def getFile(repository, filePath, branch="master"):
    response = codecommit.get_file(
                repositoryName=repository,
                commitSpecifier=branch,
                filePath=filePath
            )
    content = response['fileContent']
    return content


def registerSchemaInGsr(repoName, manifestFilePath, avroSchemaFilePath):
    doTriggerBuild = False
    
    #Read manifest.yml file
    content = getFile(repoName,manifestFilePath)
    manifest_content = yaml.full_load(content)
    print(manifest_content)
    
    #Read avroSchema
    avroSchema = getFile(repoName,avroSchemaFilePath)
    avroSchema = json.loads(avroSchema)
    avroSchemaStr = json.dumps(avroSchema)
    print(avroSchemaStr)
    
    try:
        #Create schema
        response = gsr.create_schema(
            RegistryId={
                'RegistryName': manifest_content['gsr']['registry']['name']
            },
            SchemaName=manifest_content['gsr']['schema']['name'],
            DataFormat=manifest_content['gsr']['schema']['data_format'],
            Compatibility=manifest_content['gsr']['schema']['compatibility_mode'],
            Description=manifest_content['gsr']['schema']['description'],
            SchemaDefinition=avroSchemaStr
        )
        print("Created new schema - " + manifest_content['gsr']['schema']['name'])
        
        #Handle malformed schema
        doTriggerBuild = True
    except BaseException as ex:
        print(type(ex))
        #Register schema version in GSR
        print("Register new schema version")
        registerResponse = gsr.register_schema_version(
            SchemaId={
                'SchemaName': manifest_content['gsr']['schema']['name'],
                'RegistryName': manifest_content['gsr']['registry']['name']
            },
            SchemaDefinition=avroSchemaStr
        )

        if registerResponse['Status'] == "AVAILABLE":
            doTriggerBuild = True
        else:
            #If failed to register schema version, delete the version
            print("Delete schema version as the version registration failed")
            delResponse = gsr.delete_schema_versions(
                SchemaId={
                    'SchemaName': manifest_content['gsr']['schema']['name'],
                    'RegistryName': manifest_content['gsr']['registry']['name']
                },
                Versions=str(registerResponse['VersionNumber'])
            )

    return doTriggerBuild

def lambda_handler(event, context):

    # Initialize needed variables
    fileNames_allowed = ["^.*\.(avsc)$"]
    commit_hash = event['Records'][0]['codecommit']['references'][0]['commit']
    region = event['Records'][0]['awsRegion']
    repo_name = event['Records'][0]['eventSourceARN'].split(':')[-1]
    account_id = event['Records'][0]['eventSourceARN'].split(':')[4]
    branchName = os.path.basename(
        str(event['Records'][0]['codecommit']['references'][0]['ref']))

    # Get commit ID for fetching the commit log
    if (commit_hash == None) or (commit_hash == '0000000000000000000000000000000000000000'):
        commit_hash = getLastCommitID(repo_name, branchName)

    lastCommit = getLastCommitLog(repo_name, commit_hash)

    previousCommitID = None
    if len(lastCommit['parents']) > 0:
        previousCommitID = lastCommit['parents'][0]

    print('lastCommitID: {0} previousCommitID: {1}'.format(
        commit_hash, previousCommitID))

    differences = getFileDifferences(repo_name, commit_hash, previousCommitID)


    # Check whether any avro file is added/modified
    # Register the schema in GSR
    # and set flag for build triggering
    doTriggerBuild = False
    for diff in differences:
        if 'afterBlob' in diff:
            schemaFileName = os.path.basename(str(diff['afterBlob']['path']))
            avroSchemaFilePath = AVRO_FILE_PATH + schemaFileName
            
            #find match for files with avro extension
            for fa in fileNames_allowed:
                if re.search(fa, schemaFileName):
                    doTriggerBuild = registerSchemaInGsr(repo_name, MANIFEST_FILE_PATH, avroSchemaFilePath)


    # Trigger codebuild job to build the repository if needed
    if doTriggerBuild:
        build = {
            'projectName': CODE_BUILD_PROJECT,
            'sourceVersion': commit_hash,
            'sourceTypeOverride': 'CODECOMMIT',
            'sourceLocationOverride': 'https://git-codecommit.%s.amazonaws.com/v1/repos/%s' % (region, repo_name)
        }

        print("Building schema from repo %s in region %s" % (repo_name, region))

        # build schema
        cb.start_build(**build)
    else:
        print('Changed files does not match any triggers. Hence build is suppressed')
    
    return 'Success.'

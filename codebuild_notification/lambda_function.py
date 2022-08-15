import boto3
import os
import re
import yaml
from botocore.exceptions import ClientError

codecommit = boto3.client('codecommit')
sns = boto3.client('sns')
gsr = boto3.client('glue')
cb = boto3.client('codebuild')

FILE_NAMES_ALLOWED = ["^.*\.(avsc)$"]
CODE_BUILD_PROJECT = os.getenv('CODE_BUILD_PROJECT')
MANIFEST_FILE_PATH = os.getenv('MANIFEST_FILE_PATH')

def getLastCommitLog(repository, commitId):
    response = codecommit.get_commit(
        repositoryName=repository,
        commitId=commitId
    )
    return response['commit']

def getFile(repository, filePath, branch="master"):
    response = codecommit.get_file(
                repositoryName=repository,
                commitSpecifier=branch,
                filePath=filePath
            )
    content = response['fileContent']
    return content

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


def getLatestSchemaVersion(schemaName, registryName):
    schemas = []

    response = gsr.list_schema_versions(
            SchemaId={
                'SchemaName': schemaName,
                'RegistryName': registryName
            },
            MaxResults=25
        )
    
    while "NextToken" in response:
        response = gsr.list_schema_versions(
            SchemaId={
                'SchemaName': schemaName,
                'RegistryName': registryName
            },
            MaxResults=25,
            NextToken=response['NextToken']
        )
        schemas += response.get("Schemas", [])
    else:
        schemas += response["Schemas"]

    schemas.sort(key=lambda x: x['VersionNumber'])
    return schemas[-1]['VersionNumber']


def deleteSchemaVersion(schemaName, registryName, versionNumber):
    response = gsr.delete_schema_versions(
            SchemaId={
                'SchemaName': schemaName,
                'RegistryName': registryName
            },
            Versions=str(versionNumber)
        )
    return response


def deleteSchema(schemaName, registryName):
    response = gsr.delete_schema(
            SchemaId={
                'SchemaName': schemaName,
                'RegistryName': registryName
            }
        )
    return response


def sendMsgToSns(repoName):
    schemaName = repoName.replace("schema-", "")

    response = readFromManifestFile(repoName)

    try:
        # List latest schema version
        latestSchemaVersion = getLatestSchemaVersion(response['schemaName'], response['registryName'])

        message = '''New version <b>{0}</b> of schema <b>{1}</b> is available!'''.format(latestSchemaVersion, schemaName)
        response = sns.publish(
                    TopicArn=os.environ["SNSTopicArn"],
                    Message=message,
                    Subject='New Schema version available'
                )
    except BaseException as ex:
        print(ex)
    return


def readFromManifestFile(repoName):
    content = getFile(repoName, MANIFEST_FILE_PATH)
    manifest_content = yaml.full_load(content)

    schemaName = manifest_content['gsr']['schema']['name']
    registryName = manifest_content['gsr']['registry']['name']

    return {
        "schemaName": schemaName,
        "registryName": registryName
    }


def deleteSchemaVersionInGsr(repoName):
    # Read manifest.yml file
    response = readFromManifestFile(repoName)

    schemaName = response['schemaName']
    registryName = response['registryName']

    try:
        # List latest schema version
        latestSchemaVersion = getLatestSchemaVersion(schemaName, registryName)
        
        # Delete schema version
        deleteResponse = deleteSchemaVersion(schemaName, registryName, latestSchemaVersion)
        print("Deleted schema version %s-%s" % (schemaName, latestSchemaVersion))
    except gsr.exceptions.InvalidInputException as ex:
        print(str(ex))
        if "Cannot delete checkpoint version" in str(ex):
            deleteResponse = deleteSchema(schemaName, registryName)
            print("Deleted schema %s" % (schemaName))
    except BaseException as ex:
        print(ex)

    return


def getCommitDifferences(buildId, repoName):
    try:
        buildDetails = cb.batch_get_builds(ids=[buildId])
        commitId = buildDetails['builds'][0]['sourceVersion']
        repoName = repoName[repoName.rfind("/")+1:]

        lastCommit = getLastCommitLog(repoName, commitId)

        previousCommitId = None
        if len(lastCommit['parents']) > 0:
            previousCommitId = lastCommit['parents'][0]

        print('lastCommitID: {0} previousCommitID: {1}'.format(commitId, previousCommitId))

        differences = getFileDifferences(repoName, commitId, previousCommitId)

    except BaseException as ex:
        print(ex)

    return differences


def lambda_handler(event, context):
    print(event)

    repoName = event['repository'][event['repository'].rfind("/")+1:]
    
    if event['build-status'] == 'SUCCEEDED':
        sendMsgToSns(repoName)
    else:
        # Delete latest GSR schema version only if the commit has changes in AVRO file
        # This is because if a build is triggered because of other reasons (previous failure, manual), new schema versions won't be created. 
        # In that case deleting schema version due to build failure will result in loss of schema versions from GSR.
        
        # Get differences between current and previous build.
        differences = getCommitDifferences(event['build-id'], repoName)

        # If the difference is in a AVRO file it means last build was triggered because of change in AVRO files
        for diff in differences:
            if 'afterBlob' in diff:
                schemaFileName = os.path.basename(str(diff['afterBlob']['path']))
                   
                for fa in FILE_NAMES_ALLOWED:
                    if re.search(fa, schemaFileName):
                        # Delete latest schema version from GSR
                        deleteSchemaVersionInGsr(repoName)

    return
package com.amazonaws.msk.samples;


import com.amazonaws.services.schemaregistry.serializers.GlueSchemaRegistryKafkaSerializer;
import com.amazonaws.services.schemaregistry.utils.AWSSchemaRegistryConstants;
import com.amazonaws.services.schemaregistry.utils.AvroRecordType;
import com.github.javafaker.Faker;
import org.apache.kafka.clients.CommonClientConfigs;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.config.SaslConfigs;
import org.apache.kafka.common.errors.SerializationException;
import org.apache.kafka.common.serialization.StringSerializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import pojo.customer.customer;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.glue.model.DataFormat;
import software.amazon.awssdk.services.sts.StsClient;
import software.amazon.awssdk.services.sts.model.AssumeRoleRequest;
import software.amazon.awssdk.services.sts.model.AssumeRoleResponse;
import software.amazon.awssdk.services.sts.model.Credentials;
import software.amazon.awssdk.services.sts.model.StsException;

import java.util.Properties;

public class Producer
{
    private final static Logger logger = LoggerFactory.getLogger(Producer.class);

    public static void main(String[] args) {
        //Setting properties for Apache kafka (MSK) and Glue Schema Registry
        Properties props = new Properties();

        props.setProperty(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "boot-9ganydcu.c2.kafka-serverless.us-east-1.amazonaws.com:9098");
        props.setProperty(ProducerConfig.ACKS_CONFIG, "all");
        props.setProperty(ProducerConfig.CLIENT_ID_CONFIG,"producer.properties");
        props.setProperty(CommonClientConfigs.SECURITY_PROTOCOL_CONFIG, "SASL_SSL");
        props.setProperty(SaslConfigs.SASL_MECHANISM, "AWS_MSK_IAM");
        props.setProperty(SaslConfigs.SASL_JAAS_CONFIG, "software.amazon.msk.auth.iam.IAMLoginModule required;");
        props.setProperty(SaslConfigs.SASL_CLIENT_CALLBACK_HANDLER_CLASS, "software.amazon.msk.auth.iam.IAMClientCallbackHandler");
        props.setProperty(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.setProperty(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, GlueSchemaRegistryKafkaSerializer.class.getName());

        props.setProperty(AWSSchemaRegistryConstants.DATA_FORMAT, DataFormat.AVRO.name());
        props.setProperty(AWSSchemaRegistryConstants.AWS_REGION,"us-east-1");
        props.setProperty(AWSSchemaRegistryConstants.REGISTRY_NAME, "enterprise_schemas");
        props.setProperty(AWSSchemaRegistryConstants.SCHEMA_NAME, "customer");
        props.setProperty(AWSSchemaRegistryConstants.AVRO_RECORD_TYPE, AvroRecordType.SPECIFIC_RECORD.getName());

        assumeGlueSchemaRegistryRole();
        KafkaProducer<String, customer> producer = new KafkaProducer<>(props);
        logger.info("Starting to send records...");

        Faker faker = new Faker();
        customer customer = new customer();
        try {
            for(int i = 0; i < 5; i ++)
            {
                customer.setFirstName(faker.name().firstName());
                customer.setLastName(faker.name().lastName());
                ProducerRecord<String, customer> record = new ProducerRecord<>("customer", customer);
                producer.send(record);
                logger.info("Sent message #" + i);
                Thread.sleep(1000L);
            }
        producer.flush();
        } catch(final InterruptedException | SerializationException e) {
            e.printStackTrace();
        }
    }


    public static void assumeGlueSchemaRegistryRole() {
        try {
            Region region = Region.of("us-east-1");
//            if(!Region.regions().contains(region))
//                throw new RuntimeException("Region : " + regionName + " is invalid.");
            StsClient stsClient = StsClient.builder().region(region).build();
            AssumeRoleRequest roleRequest = AssumeRoleRequest.builder()
                    .roleArn("arn:aws:iam::940270119111:role/msksls-clickstream-EC2Role-11M4I4VE59TGV")
                    .roleSessionName("kafka-producer-cross-account-glue-schemaregistry-demo")
                    .build();
            AssumeRoleResponse roleResponse = stsClient.assumeRole(roleRequest);
            Credentials myCreds = roleResponse.credentials();
            System.setProperty("aws.accessKeyId", myCreds.accessKeyId());
            System.setProperty("aws.secretAccessKey", myCreds.secretAccessKey());
            System.setProperty("aws.sessionToken", myCreds.sessionToken());
            stsClient.close();
        } catch (StsException e) {
            logger.error(e.getMessage());
            System.exit(1);
        }
    }
}

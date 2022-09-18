package com.amazonaws.msk.samples;

import com.amazonaws.services.schemaregistry.deserializers.GlueSchemaRegistryKafkaDeserializer;
import com.amazonaws.services.schemaregistry.utils.AWSSchemaRegistryConstants;
import com.amazonaws.services.schemaregistry.utils.AvroRecordType;
import org.apache.kafka.clients.CommonClientConfigs;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.config.SaslConfigs;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import pojo.customer.Customer;

import java.time.Duration;
import java.util.Collections;
import java.util.Properties;

public class Consumer
{
    private final static Logger logger = LoggerFactory.getLogger(Producer.class);

    public static void main(String[] args) {
        //Setting properties for Apache kafka (MSK) and Glue Schema Registry
        Properties props = new Properties();

        props.setProperty(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "boot-9ganydcu.c2.kafka-serverless.us-east-1.amazonaws.com:9098");
        props.setProperty(ConsumerConfig.GROUP_ID_CONFIG,"customer.consumer");
        props.setProperty(ConsumerConfig.CLIENT_ID_CONFIG,"consumer.properties");
        props.setProperty(CommonClientConfigs.SECURITY_PROTOCOL_CONFIG, "SASL_SSL");
        props.setProperty(SaslConfigs.SASL_MECHANISM, "AWS_MSK_IAM");
        props.setProperty(SaslConfigs.SASL_JAAS_CONFIG, "software.amazon.msk.auth.iam.IAMLoginModule required;");
        props.setProperty(SaslConfigs.SASL_CLIENT_CALLBACK_HANDLER_CLASS, "software.amazon.msk.auth.iam.IAMClientCallbackHandler");
        props.setProperty(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.setProperty(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, GlueSchemaRegistryKafkaDeserializer.class.getName());

        props.setProperty(AWSSchemaRegistryConstants.AWS_REGION,"us-east-1");
        props.setProperty(AWSSchemaRegistryConstants.AVRO_RECORD_TYPE, AvroRecordType.SPECIFIC_RECORD.getName());

        logger.info("Starting to consume records...");

        KafkaConsumer<String, Customer> consumer = new KafkaConsumer<>(props);
        consumer.subscribe(Collections.singletonList("customer"));

        int count = 1;
        while (true) {
            final ConsumerRecords<String, Customer> records = consumer.poll(Duration.ofMillis(1000));
            for (final ConsumerRecord<String, Customer> record : records) {
                final Customer customer = record.value();
                logger.info("Record #" + count + ": "+ customer.getFirstName().toString() + " " + customer.getLastName().toString());
                count++;
            }
        }
    }
}

from google.cloud import pubsub

local_pubsub = pubsub.Client('acuit-renfei-sandbox')
feed_topic = local_pubsub.topic('gl2.feed')
rerequest_topic = local_pubsub.topic('gl2.request')
status_topic = local_pubsub.topic('gl2.status')

if not feed_topic.exists():
    print("Creating feed topic.")
    feed_topic.create()

if not rerequest_topic.exists():
    print("Creating rerequest topic and subscription.")
    rerequest_topic.create()
    rerequest_topic.subscription("request").create()

if not status_topic.exists():
    print("Creating status topic.")
    status_topic.create()

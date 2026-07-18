from neos.coding.transport.memory import InProcessCodingEventBroker

__all__ = ["InProcessCodingEventBroker", "coding_event_broker"]


coding_event_broker = InProcessCodingEventBroker()

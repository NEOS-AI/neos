from neos.coding.transport.memory import InMemoryWsTicketStore, WsTicket

__all__ = ["InMemoryWsTicketStore", "WsTicket", "ws_ticket_store"]


ws_ticket_store = InMemoryWsTicketStore()

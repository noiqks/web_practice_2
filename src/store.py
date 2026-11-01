import time

from src.models import Client, Message, Output


class SqliteStore:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def add_client(self, platform, user_agent):
        session = self.session_factory()

        try:
            client = Client(
                created=int(time.time()),
                platform=platform,
                user_agent=user_agent,
            )
            session.add(client)
            session.commit()
            session.refresh(client)
            return self.client_to_dict(client)
        finally:
            session.close()

    def get_clients(self, filters):
        session = self.session_factory()

        try:
            query = session.query(Client)

            for field, value in filters.items():
                if value is not None:
                    query = query.filter(
                        getattr(Client, field) == value
                    )

            return [
                self.client_to_dict(client)
                for client in query.all()
            ]
        finally:
            session.close()

    def update_client(self, uid, values):
        session = self.session_factory()

        try:
            client = session.get(Client, uid)

            if client is None:
                return None

            for field, value in values.items():
                setattr(client, field, value)

            session.commit()
            session.refresh(client)
            return self.client_to_dict(client)
        finally:
            session.close()

    def get_client(self, uid):
        session = self.session_factory()

        try:
            client = session.get(Client, uid)

            if client is None:
                return None

            return self.client_to_dict(client)
        finally:
            session.close()

    def add_message(self, payload, client, tags, stage, launched):
        session = self.session_factory()

        try:
            message = Message(
                created=int(time.time()),
                payload=payload,
                client=client,
                tags=tags,
                stage=stage,
                launched=launched,
            )
            session.add(message)
            session.commit()
            session.refresh(message)
            return self.message_to_dict(message)
        finally:
            session.close()

    def get_messages(self, client_uid, filters):
        session = self.session_factory()

        try:
            query = session.query(Message).filter(
                Message.client == client_uid
            )

            for field, value in filters.items():
                if value is not None:
                    query = query.filter(
                        getattr(Message, field) == value
                    )

            return [
                self.message_to_dict(message)
                for message in query.all()
            ]
        finally:
            session.close()

    def update_message(self, uid, values):
        session = self.session_factory()

        try:
            message = session.get(Message, uid)

            if message is None:
                return None

            for field, value in values.items():
                setattr(message, field, value)

            session.commit()
            session.refresh(message)
            return self.message_to_dict(message)
        finally:
            session.close()

    def get_message(self, uid):
        session = self.session_factory()

        try:
            message = session.get(Message, uid)

            if message is None:
                return None

            return self.message_to_dict(message)
        finally:
            session.close()

    def add_output(self, message, response, stage, failure, cache_hit=0):
        session = self.session_factory()

        try:
            output = Output(
                created=int(time.time()),
                message=message,
                response=response,
                stage=stage,
                failure=failure,
                cache_hit=cache_hit,
            )
            session.add(output)
            session.commit()
            session.refresh(output)
            return self.output_to_dict(output)
        finally:
            session.close()

    def get_outputs(self, message_uid, filters):
        session = self.session_factory()

        try:
            query = session.query(Output).filter(
                Output.message == message_uid
            )

            for field, value in filters.items():
                if value is not None:
                    query = query.filter(
                        getattr(Output, field) == value
                    )

            return [
                self.output_to_dict(output)
                for output in query.all()
            ]
        finally:
            session.close()

    def update_output(self, uid, values):
        session = self.session_factory()

        try:
            output = session.get(Output, uid)

            if output is None:
                return None

            for field, value in values.items():
                setattr(output, field, value)

            session.commit()
            session.refresh(output)
            return self.output_to_dict(output)
        finally:
            session.close()

    def get_report(self, cutoff):
        session = self.session_factory()

        try:
            rows = (
                session.query(Client, Message)
                .join(Message, Client.uid == Message.client)
                .filter(Client.created >= cutoff)
                .all()
            )

            return [
                {
                    "user_agent": client.user_agent,
                    "payload": message.payload,
                    "tags": message.tags,
                }
                for client, message in rows
            ]
        finally:
            session.close()

    @staticmethod
    def client_to_dict(client):
        return {
            "uid": client.uid,
            "created": client.created,
            "platform": client.platform,
            "user_agent": client.user_agent,
        }

    @staticmethod
    def message_to_dict(message):
        return {
            "uid": message.uid,
            "created": message.created,
            "payload": message.payload,
            "client": message.client,
            "tags": message.tags,
            "stage": message.stage,
            "launched": message.launched,
        }

    @staticmethod
    def output_to_dict(output):
        return {
            "uid": output.uid,
            "created": output.created,
            "response": output.response,
            "stage": output.stage,
            "failure": output.failure,
            "message": output.message,
            "cache_hit": output.cache_hit,
        }
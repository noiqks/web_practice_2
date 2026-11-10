from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

DEFAULT_CACHE_HIT = 0

Base = declarative_base()


class Client(Base):
    __tablename__ = "clients"

    uid = Column(Integer, primary_key=True)
    created = Column(Integer, nullable=False)
    platform = Column(String, nullable=False)
    user_agent = Column(String, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    uid = Column(Integer, primary_key=True)
    created = Column(Integer, nullable=False)
    payload = Column(String, nullable=False)
    client = Column(Integer, nullable=False)
    tags = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    launched = Column(Integer, nullable=False)


class Output(Base):
    __tablename__ = "outputs"

    uid = Column(Integer, primary_key=True)
    created = Column(Integer, nullable=False)
    response = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    failure = Column(String, nullable=False)
    message = Column(Integer, nullable=False)
    cache_hit = Column(
        Integer,
        nullable=False,
        default=DEFAULT_CACHE_HIT,
    )

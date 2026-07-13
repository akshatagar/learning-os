from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def get_engine(path):
    return create_engine(f"sqlite:///{path}")


def get_session(engine):
    return Session(engine)

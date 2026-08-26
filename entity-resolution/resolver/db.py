"""Connection helper for the meridianComposite composite database.

Kept deliberately thin: everything else in this package takes a `session`
object (anything with a `.run(query, **params)` method, matching the
neo4j driver's Session interface) so it can be unit tested with a fake/mock
session instead of a live database.
"""
import os

from neo4j import GraphDatabase


def get_driver():
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(user, password))


def get_session(driver):
    database = os.environ.get("NEO4J_COMPOSITE_DB", "meridiancomposite")
    return driver.session(database=database)

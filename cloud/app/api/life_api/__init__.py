"""Web API for the حياتي tab, split by domain (shopping/habits/expenses/journal/
books-reading/scenes-focus). Public surface unchanged:
register_life_api(app, mongo_db=...) still registers every route.
"""
from app.api.life_api.shopping import _register_shopping
from app.api.life_api.habits import _register_habits
from app.api.life_api.expenses import _register_expenses
from app.api.life_api.journal import _register_journal
from app.api.life_api.books import _register_books
from app.api.life_api.scenes import _register_scenes


def register_life_api(app, mongo_db=None):
    _register_shopping(app)
    _register_habits(app)
    _register_expenses(app)
    _register_journal(app)
    _register_books(app)
    _register_scenes(app)

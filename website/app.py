"""PharmaCare DBMS - Pharmacy Management System (Flask).

Run:  python app.py            (http://127.0.0.1:5000)
CLI:  flask --app app init-db  (recreate tables, empty)
      flask --app app seed     (recreate tables + demo data)
"""
import datetime

import click
from flask import Flask, render_template

import utils
from config import Config
from db import Database, close_db, ensure_database, get_db


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    app.teardown_appcontext(close_db)

    from routes import register_blueprints

    register_blueprints(app)

    app.jinja_env.filters.update(
        money=utils.fmt_money,
        num=utils.fmt_num,
        date=utils.fmt_date,
        datetime=utils.fmt_datetime,
        initials=utils.initials,
        code=utils.code,
    )
    app.jinja_env.globals.update(
        days_until=utils.days_until,
        age_from=utils.age_from,
        stock_status=utils.stock_status,
        url_with=utils.url_with,
    )

    @app.context_processor
    def inject_shell():
        """Counts shown in the sidebar/top bar on every page."""
        try:
            db = get_db()
            today = datetime.date.today()
            soon = (today + datetime.timedelta(days=app.config["EXPIRY_SOON_DAYS"])).isoformat()
            counts = db.one(
                "SELECT "
                " (SELECT COUNT(*) FROM medicines) AS medicines,"
                " (SELECT COUNT(*) FROM categories) AS categories,"
                " (SELECT COUNT(*) FROM suppliers) AS suppliers,"
                " (SELECT COUNT(*) FROM customers) AS customers,"
                " (SELECT COUNT(*) FROM purchases) AS purchases,"
                " (SELECT COUNT(*) FROM medicines WHERE stock_quantity <= reorder_level"
                "    OR expiry_date <= ?) AS alerts",
                (soon,),
            )
            all_categories = db.query("SELECT category_id, category_name FROM categories ORDER BY category_name")
            db_ok = True
        except Exception:  # keep error pages renderable even if the DB is down
            counts, all_categories, db_ok = {}, [], False
        return {
            "nav_counts": counts or {},
            "all_categories": all_categories,
            "db_ok": db_ok,
            "db_engine": "MySQL" if app.config["DB_ENGINE"] == "mysql" else "SQLite",
            "currency": app.config["CURRENCY"],
            "tax_rate": app.config["TAX_RATE"],
            "pharmacy_name": app.config["PHARMACY_NAME"],
            "today": datetime.date.today(),
        }

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, title="Page not found",
                               message="The page or record you requested does not exist."), 404

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500, title="Something went wrong",
                               message="The server hit an unexpected error. Check the database connection."), 500

    @app.cli.command("init-db")
    def init_db_command():
        """Drop and recreate all tables (no data)."""
        db = Database(app.config)
        db.init_schema()
        db.close()
        click.echo(f"Initialized empty {app.config['DB_ENGINE']} schema.")

    @app.cli.command("seed")
    def seed_command():
        """Drop and recreate all tables, then load demo data."""
        from seed import seed_demo_data

        db = Database(app.config)
        db.init_schema()
        seed_demo_data(db)
        db.close()
        click.echo(f"Loaded demo data into {app.config['DB_ENGINE']}.")

    ensure_database(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

def register_blueprints(app):
    from . import (alerts, categories, customers, dashboard, medicines, purchases, reports,
                   sales, suppliers, system)

    for module in (dashboard, medicines, categories, suppliers, customers, purchases, sales,
                   alerts, reports, system):
        app.register_blueprint(module.bp)

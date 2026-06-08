from flask_pymongo import PyMongo

# Global mongo instance
mongo = PyMongo()

def init_db(app):
    """
    Initialize MongoDB connection with strict resource limits for NoSQL Atlas Free Tier.
    We set maxPoolSize=2 to avoid threading deadlocks in a 1 CPU container.
    """
    try:
        mongo.init_app(
            app, 
            maxPoolSize=2, 
            serverSelectionTimeoutMS=20000, 
            connectTimeoutMS=20000,
            socketTimeoutMS=20000
        )
    except Exception as e:
        print(f"FAILED TO CONNECT TO MONGODB ATLAS: {e}")

def get_db():
    """
    Returns the current database instance.
    """
    return mongo.db

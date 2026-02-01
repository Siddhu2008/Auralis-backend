import dns.resolver
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

def connect_with_custom_dns():
    uri = os.getenv('MONGO_URI')
    print(f"Testing URI: {uri[:30]}...")

    # Configure the default resolver for dnspython
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ['8.8.8.8']
    dns.resolver.default_resolver = resolver

    try:
        print("Connecting with custom resolver...")
        client = MongoClient(uri, serverSelectionTimeoutMS=10000)
        print("Pinging admin...")
        res = client.admin.command('ping')
        print(f"Success! Ping response: {res}")
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

if __name__ == "__main__":
    connect_with_custom_dns()

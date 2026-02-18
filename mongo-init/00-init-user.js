// MongoDB initialization script
// This creates the application user and database

db = db.getSiblingDB('supply_bill_db');

// Create a user for the application
db.createUser({
  user: 'app_user',
  pwd: 'app_password',
  roles: [
    {
      role: 'readWrite',
      db: 'supply_bill_db'
    }
  ]
});

print('Database and user initialized successfully');
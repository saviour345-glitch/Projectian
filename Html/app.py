from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

USERNAME = 'saviour'
PASSWORD = '1234'

@app.route('/')
def home():
    return render_template ("index.html")

@app.route('/login', methods= ["GET", "POST"])
def login():
    Username = request.form['username']
    Password = request.form['password']

    if USERNAME == Username and PASSWORD == Password:
        return render_template('success.html')
    else:
        return('Incorrect username or password!')
@app.route('/success')
def success():
    return render_template("success.html")

if __name__== '__main__':
    app.run(debug = True)

    

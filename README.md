# Technical example

https://github.com/Joel-Rasch/Two-Phase-Commit

## What is the example

This is a Webapp with a Flask backend and Postgres Databases to implement a two phase commit for a bank

You can create a account with unique ids and a starting balance

You can transfer money from one iban to another there are various checks like unique iban and that the balance could not go under 0

All commits are distributed to all connected databases

## How to use
- To start download the Repo
- Start Docker
- go to the folder where the files are and open powershell or bash
- now run 'docker-compose up --build'
- to build the Docker image
- in your Browser open 127.0.0.1:5000 to open the Frontend of this example

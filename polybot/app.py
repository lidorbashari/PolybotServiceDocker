import flask
from flask import request
import os
from bot import ObjectDetectionBot
import boto3
from dotenv import load_dotenv
load_dotenv()

app = flask.Flask(__name__)

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
TELEGRAM_APP_URL = os.environ['TELEGRAM_APP_URL']
S3_BUCKET_NAME = os.environ['S3_BUCKET_NAME']
S3_REGION = os.environ['S3_REGION']
s3_client = boto3.client('s3')
bot = ObjectDetectionBot(TELEGRAM_TOKEN, TELEGRAM_APP_URL, S3_BUCKET_NAME, S3_REGION, s3_client)



@app.route('/', methods=['GET'])
def index():
    return 'Ok'


@app.route(f'/{TELEGRAM_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8443)

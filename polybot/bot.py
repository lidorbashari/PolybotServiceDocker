import telebot
from loguru import logger
import os
import time
import requests
from telebot.types import InputFile
import boto3


class Bot:

    def __init__(self, telegram_token, telegram_chat_url, s3_bucket_name, s3_region, s3_client=None):
        self.telegram_bot_client = telebot.TeleBot(telegram_token)
        self.S3_BUCKET_NAME = s3_bucket_name
        self.S3_REGION = s3_region
        if s3_client:
            self.s3_client = s3_client
        else:
            self.s3_client = boto3.client('s3', region_name=self.S3_REGION)

        # remove any existing webhooks configured in Telegram servers
        self.telegram_bot_client.remove_webhook()
        time.sleep(0.5)

        # set the webhook URL
        self.telegram_bot_client.set_webhook(url=f'{telegram_chat_url}/{token}/', timeout=60)

        logger.info(f'Telegram Bot information\n\n{self.telegram_bot_client.get_me()}')

    def send_text(self, chat_id, text):
        self.telegram_bot_client.send_message(chat_id, text)

    def send_text_with_quote(self, chat_id, text, quoted_msg_id):
        self.telegram_bot_client.send_message(chat_id, text, reply_to_message_id=quoted_msg_id)

    def is_current_msg_photo(self, msg):
        return 'photo' in msg

    def download_user_photo(self, msg):
        """
        Downloads the photos that sent to the Bot to `photos` directory (should be existed)
        :return:
        """
        if not self.is_current_msg_photo(msg):
            raise RuntimeError(f'Message content of type \'photo\' expected')

        file_info = self.telegram_bot_client.get_file(msg['photo'][-1]['file_id'])
        data = self.telegram_bot_client.download_file(file_info.file_path)
        folder_name = file_info.file_path.split('/')[0]

        if not os.path.exists(folder_name):
            os.makedirs(folder_name)

        with open(file_info.file_path, 'wb') as photo:
            photo.write(data)

        return file_info.file_path

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            raise RuntimeError("Image path doesn't exist")

        self.telegram_bot_client.send_photo(
            chat_id,
            InputFile(img_path)
        )

    def handle_message(self, msg):
        """Bot Main message handler"""
        logger.info(f'Incoming message: {msg}')
        self.send_text(msg['chat']['id'], f'Your original message: {msg["text"]}')


class ObjectDetectionBot(Bot):
    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        chat_id = msg['chat']['id']
        text = msg.get('text', '')
        if self.is_current_msg_photo(msg):
            self.process_photo_message(msg)
        else:
            self.send_text(msg['chat']['id'], "תכניס תמונה בבקשה")

    def process_photo_message(self, msg):
        try:
            # Trying to download the photo
            photo_path = self.download_user_photo(msg)
            self.send_text(msg['chat']['id'], f'Photo downloaded to: {photo_path}')

            # Upload photo to S3
            self.upload_photo_s3(str(photo_path))
            logger.info(f'Trying to upload photo to S3')
            self.send_text(msg['chat']['id'], "Photo uploaded to S3.")

            # Post request to YOLOv5
            img_name = os.path.basename(photo_path)
            logger.info(f"Sending image {img_name} to YOLOv5 for prediction.")
            prediction_result = self.send_to_yolo5(img_name, msg)


            if prediction_result:
                logger.info(f"Prediction result: {prediction_result}")

                #  if 'predicted_img_path' in prediction_result:
                #    predicted_image_path = prediction_result.get('predicted_img_path', '')
                #    predicted_image_url = f"https://{self.S3_BUCKET_NAME}.s3.amazonaws.com/{predicted_image_path}"
                #    self.send_text(msg['chat']['id'], f"Prediction completed: {predicted_image_url}")

                if 'labels' in prediction_result:
                    labels = prediction_result['labels']
                    label_counts = {}
                    for label in labels:
                        label_class = label['class']
                        if label_class in label_counts:
                            label_counts[label_class] += 1
                        else:
                            label_counts[label_class] = 1
                    formatted_result = '\n'.join([f'{label}: {count}' for label, count in label_counts.items()])

                    self.send_text(msg['chat']['id'], f'Detected lidor objects:\n {formatted_result}')
                else:
                    self.send_text(msg['chat']['id'], "No objects detected in the image.")
            else:
                 logger.info(f"No prediction result was found from yolo5")
                 self.send_text(msg['chat']['id'], "Sorry, there was an issue processing the image.")


        except Exception as e:
            logger.error(f"Error processing photo message: {e}")
            self.send_text(msg['chat']['id'], "An error occurred while processing your photo.")

    def upload_photo_s3(self, file_path):
        try:
            file_name = os.path.basename(file_path)
            s3_file_path = f"predictions/{file_name}"
            self.s3_client.upload_file(file_path, self.S3_BUCKET_NAME, s3_file_path)
            logger.info(f"File uploaded to S3: {s3_file_path}")
        except Exception as e:
            logger.error(f"Failed to upload photo to S3: {e}")
            raise

    def send_to_yolo5(self, img_name, msg):
        try:
            url = f'http://localhost:8081/predict'
            logger.info(f"Sending image {img_name} to YOLOv5 for prediction.")

            # Send image name to the YOLOv5 API
            response = requests.post(
                url,
                params={"imgName": f"predictions/{img_name}"}
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            response_data = response.json()

            # לוג של ה-response שמתקבל מ-YOLOv5
            logger.info(f"Response from YOLOv5: {response.status_code} - {response.text}")

            # check if response is okay and return
            if response.status_code == 200:
                return response_data
            else:
                logger.error(f"Error with prediction: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send to YOLOv5: {e}")
            return None
import time
from pathlib import Path
from flask import Flask, request
from detect import run
import uuid
from pymongo import MongoClient
import yaml
import boto3
from loguru import logger
import os

images_bucket = os.environ['BUCKET_NAME']

with open("data/coco128.yaml", "r") as stream:
    names = yaml.safe_load(stream)['names']

app = Flask(__name__)

@app.route('/predict', methods=['POST'])
def predict():
    # Generates a UUID for this current prediction HTTP request.
    prediction_id = str(uuid.uuid4())
    logger.info(f'prediction: {prediction_id}. start processing')

    # Receives a URL parameter representing the image to download from S3
    img_name = request.args.get('imgName')

    # Create /tmp/predictions directory if it doesn't exist
    tmp_dir = "/tmp"
    os.makedirs(tmp_dir, exist_ok=True)

    tmp_predictions_dir = os.path.join(tmp_dir, "predictions")
    os.makedirs(tmp_predictions_dir, exist_ok=True)

    # Use only the base name of the file
    img_name_basename = os.path.basename(img_name)
    original_img_path = os.path.join(tmp_predictions_dir, img_name_basename)

    # Download the file from S3
    s3 = boto3.client('s3')
    try:
        s3.download_file(images_bucket, img_name, original_img_path)
        logger.info(f'prediction: {prediction_id}. Downloaded {img_name} to {original_img_path}')
    except Exception as e:
        logger.error(f'Error downloading {img_name}: {e}')
        return f"Error downloading {img_name}: {e}", 500

    # Predicts the objects in the image
    run(
        weights='yolov5s.pt',
        data='data/coco128.yaml',
        source=original_img_path,
        project='static/data',
        name=prediction_id,
        save_txt=True
    )

    logger.info(f'prediction: {prediction_id}/{original_img_path}. done')

    # Path for the predicted image with labels
    predicted_img_path = f'static/data/{prediction_id}/{img_name_basename}'

    # Specify the local file and S3 bucket details
    s3_image_key_upload = f'predictions/image.jpg'

    try:
        # Upload predicted image back to S3
        s3.upload_file(str(predicted_img_path), images_bucket, s3_image_key_upload)
        logger.info(f"File uploaded successfully to {images_bucket}/{s3_image_key_upload}")
    except FileNotFoundError:
        logger.error("The file was not found.")
        return "Predicted image not found", 404
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return f"Error uploading file: {e}", 500

    # Parse prediction labels and create a summary
    pred_summary_path = Path(f'static/data/{prediction_id}/labels/{Path(original_img_path).stem}.txt')
    if pred_summary_path.exists():
        with open(pred_summary_path) as f:
            labels = f.read().splitlines()
            labels = [line.split(' ') for line in labels]
            labels = [{
                'class': names[int(l[0])],
                'cx': float(l[1]),
                'cy': float(l[2]),
                'width': float(l[3]),
                'height': float(l[4]),
            } for l in labels]

        logger.info(f'prediction: {prediction_id}/{original_img_path}. prediction summary:\n\n{labels}')

        prediction_summary = {
            'prediction_id': prediction_id,
            'original_img_path': original_img_path,
            'predicted_img_path': predicted_img_path,
            'labels': labels,
            'time': time.time()
        }

        # Connect to MongoDB
        client = MongoClient('mongodb://Mongo1:27017,Mongo2:27018,Mongo3:27019/?replicaSet=myReplicaSet')

        # Select the database and collection
        db = client["yolov5"]
        collection = db["detections"]

        # Insert the prediction_summary into MongoDB
        try:
            collection.insert_one(prediction_summary)
        except Exception as e:
            logger.error(f"Error inserting to MongoDB: {e}")
            return f"Error inserting to MongoDB: {e}", 500

        if "_id" in prediction_summary:
            prediction_summary["_id"] = str(prediction_summary["_id"])

        return prediction_summary
    else:
        return f'prediction: {prediction_id}/{original_img_path}. prediction result not found', 404


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8081)

FROM python:3.9-slim

# This Dockerfile is used to run the evaluation for nl2postcondition (see the file run_postcondition_evaluation.py)
# To use this to generate new samples, you will need to modify the copy section to have the postconditions you generated in the container
# install git
RUN apt-get update
RUN apt-get install -y git unzip

# upgrade to latest pip
RUN pip install --upgrade pip

RUN mkdir SpiCoder
WORKDIR /SpiCoder
COPY requirements.txt /SpiCoder/requirements.txt
RUN pip install -r "requirements.txt"

FROM python:3.12

WORKDIR /usr/local/website-builder

COPY . .

# See this thread for why this hack in necessary
#   https://github.com/yaml/pyyaml/issues/724
RUN pip install "cython<3.0.0"
RUN pip install --no-build-isolation pyyaml==5.4.1

RUN pip install --no-cache-dir -r requirements.txt

CMD [ "bash" ]
APP_MODE ?= development

ENV_DIR := ${PWD}/config
DEF_ENV_FILE := $(ENV_DIR)/.env
ENV_FILE := $(ENV_DIR)/.env.$(APP_MODE)

ifeq ($(wildcard $(DEF_ENV_FILE)),)
$(error Default environment file not found: $(DEF_ENV_FILE))
endif

ifeq ($(wildcard $(ENV_FILE)),)
$(error Environment file not found: $(ENV_FILE))
endif

include $(DEF_ENV_FILE)
include $(ENV_FILE)

export $(shell sed 's/=.*//' $(DEF_ENV_FILE))
export $(shell sed 's/=.*//' $(ENV_FILE))

CONTAINER_NAME := $(IMAGE_NAME)-container
NETWORK_NAME := $(IMAGE_NAME)-network
#PORT := $(BOT_HEALTH_CHECK_PORT):8000
IMAGE_TAG := $(shell date +%Y-%m-%d)
.PHONY: build push network run start stop restart logs exec rm clean up

build:
	docker build -t $(DOCKER_USERNAME)/$(IMAGE_NAME):$(IMAGE_TAG) .

push:
	docker push $(DOCKER_USERNAME)/$(IMAGE_NAME):$(IMAGE_TAG)

network:
	docker network create $(NETWORK_NAME) 2>/dev/null || true

run: network
	docker run -d \
		--name $(CONTAINER_NAME) \
		--network host \
		--env-file $(DEF_ENV_FILE) \
		--env-file $(ENV_FILE) \
		$(DOCKER_USERNAME)/$(IMAGE_NAME):$(IMAGE_TAG)

bash: network
	docker run -it --rm \
		--name $(CONTAINER_NAME) \
		--network host \
		--env-file $(DEF_ENV_FILE) \
		--env-file $(ENV_FILE) \
		$(DOCKER_USERNAME)/$(IMAGE_NAME):$(IMAGE_TAG) \
		/bin/bash


start:
	docker start $(CONTAINER_NAME)

stop:
	docker stop $(CONTAINER_NAME) 2>/dev/null || true

restart: stop start

logs:
	docker logs $(CONTAINER_NAME)

exec:
	docker exec -it $(CONTAINER_NAME) /bin/sh

rm:
	docker rm -f $(CONTAINER_NAME) 2>/dev/null || true

clean: rm
	docker network rm $(NETWORK_NAME) 2>/dev/null || true

up: build run


again: build push
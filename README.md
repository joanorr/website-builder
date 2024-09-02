# Website Builder

# Usage

On the host:

```
docker run -it --rm \
  --mount type=bind,src=PATH_TO_SITE,dst=/tmp/website-builder/site \
  -p 8000:8000 \
  website-builder
```

In the container shell:

```
python builder.py \
  --src=./site/src \
  --tgt=./site/site \
  --manifest=./site/manifest.yaml \
  --sitemap=./site/sitemap.yaml
```
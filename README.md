# Website Builder

# Usage

On the host:

```
docker run -it --rm \
  --mount type=bind,src=PATH_TO_SITE,dst=/tmp/site \
  -p 8000:8000 \
  website-builder
```

In the container shell:

```
python /usr/local/website-builder/builder.py \
  --src=/tmp/site/src \
  --tgt=/tmp/site/site \
  --manifest=/tmp/site/manifest.yaml \
  --sitemap=/tmp/site/sitemap.yaml
```
# Website Builder

# Usage

```
docker run --rm \
  --mount type=bind,src=PATH_TO_SITE,dst=/website \
  -p 8080:8080 \
  website-builder \
  --serve-on 8080
```

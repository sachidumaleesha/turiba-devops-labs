# Lab 1 - Ship it

- **Image:** `ghcr.io/sachidumaleesha/lab1-web:1.0`
- **Digest:** `sha256:b1bd761f3ee8763cf0a51587af958731e8563f17f274668a3dff0a0c6e3b7697`
- **Platforms:** linux/amd64, linux/arm64
- **Partner's image I ran:** `ghcr.io/REPLACE_WITH_PARTNER_USERNAME/lab1-web:1.0` (digest matched: NO)

![My partner's image running on my laptop](partner-run.png)

## Answers

### 1. Where does the kernel used by your containers come from on your laptop?

My laptop runs Windows. Docker Desktop uses the Linux kernel provided through
its WSL 2 virtual machine. The Alpine and Ubuntu containers share this kernel,
even though they have different Linux filesystems and distributions.

My `docker info` output:

```text
Docker Desktop | kernel 6.6.114.1-microsoft-standard-WSL2 | x86_64 | 8 CPUs | 8210448384 bytes
```

My Alpine `uname -r` output:

```text
6.6.114.1-microsoft-standard-WSL2
```

My Ubuntu `uname -r` output:

```text
6.6.114.1-microsoft-standard-WSL2
```

Both containers reported the same kernel version, showing that containers share
the host VM's Linux kernel.

### 2. What is the difference between `lab1-web:1.0` and `mypage`?

`lab1-web:1.0` is an image identified by the `1.0` tag. It is the reusable,
read-only template containing Alpine Linux, nginx, and my web page. `mypage` is
a specific container created and run from that image. Multiple containers can
be created from the same image.

### 3. Why did the edit survive `docker stop` but not `docker rm`?

`docker stop` only stops the container. The container and its writable layer
remain stored, so the edited `index.html` is still present when the same
container is started again.

`docker rm` deletes the container and its writable layer. A new container made
from the original nginx image therefore displays the original nginx page
because the image itself was never changed.

### 4. Why is the image much larger than the HTML page?

The image contains more than my HTML page. It also includes the Alpine Linux
filesystem, the nginx web server, required libraries, configuration files,
metadata, and all inherited image layers. These components account for most of
the image's size.
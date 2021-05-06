FROM centos/python-36-centos7

ARG version

USER root

WORKDIR /data/projects/python/

COPY requirements.txt /data/projects/python/

RUN set -eux && \
    rpm --rebuilddb && \
    rpm --import /etc/pki/rpm-gpg/RPM* && \
    yum -y install gcc gcc-c++ make openssl-devel gmp-devel mpfr-devel libmpc-devel\
    libmpcdevel libaio numactl autoconf automake libtool libffi-devel  \
    snappy snappy-devel zlib zlib-devel bzip2 bzip2-devel lz4-devel libasan lsof sysstat telnet psmisc && \
    yum clean all

RUN pip install --upgrade pip && \
    sed -i '/tensorflow>=2.4.1/d' /data/projects/python/requirements.txt && \
    sed -i '/torch==1.4.0/d' /data/projects/python/requirements.txt && \
    sed -i '/torchvision==0.5.0/d' /data/projects/python/requirements.txt && \
    sed -i '/pytorch-lightning>=1.2.1/d' /data/projects/python/requirements.txt && \
    pip install -r requirements.txt

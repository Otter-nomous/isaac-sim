FROM nvcr.io/nvidia/isaac-sim:4.5.0

# Accept EULA and privacy consent (required to run Isaac Sim)
ENV ACCEPT_EULA=Y \
    PRIVACY_CONSENT=Y

# Install custom Python dependencies using Isaac Sim's bundled Python.
# Add packages here as you introduce them (e.g. VLA model dependencies).
# RUN /isaac-sim/python.sh -m pip install \
#     pyzmq \
#     numpy \
#     opencv-python-headless

# Copy custom scripts or extensions into the container.
# COPY robot_dog_setup.py /robot_dog_setup.py
# COPY my_extension/ /isaac-sim/exts/my_extension/

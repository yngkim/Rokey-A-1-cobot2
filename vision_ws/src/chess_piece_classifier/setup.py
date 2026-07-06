from setuptools import find_packages, setup

package_name = 'chess_piece_classifier'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'numpy', 'ultralytics', 'huggingface_hub'],
    zip_safe=True,
    maintainer='rokey',
    maintainer_email='rokey@todo.todo',
    description='Side-camera piece classification (YOLO stub)',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'piece_classifier_node = chess_piece_classifier.piece_classifier_node:main',
        ],
    },
)

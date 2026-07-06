from setuptools import find_packages, setup

package_name = 'chess_occupancy'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'numpy'],
    zip_safe=True,
    maintainer='rokey',
    maintainer_email='rokey@todo.todo',
    description='Chess board occupancy grid and vision scan service',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'occupancy_node = chess_occupancy.occupancy_node:main',
            'fake_vision_node = chess_occupancy.fake_vision_node:main',
            'calibrate_empty_depth = chess_occupancy.calibrate_empty_depth:main',
        ],
    },
)

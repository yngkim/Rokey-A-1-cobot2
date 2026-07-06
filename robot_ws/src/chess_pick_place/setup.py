from setuptools import find_packages, setup

package_name = 'chess_pick_place'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rokey',
    maintainer_email='rokey@todo.todo',
    description='Pick-and-place execution and robot service/action servers',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'pick_place_node = chess_pick_place.pick_place_node:main',
            'fake_robot_node = chess_pick_place.fake_robot_node:main',
            'doosan_pick_place_node = chess_pick_place.doosan_pick_place_node:main',
        ],
    },
)

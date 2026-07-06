from setuptools import find_packages, setup

package_name = 'chess_web_ui'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/vision_manual.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rokey',
    maintainer_email='rokey@todo.todo',
    description='React web UI and HTTP bridge for chess pick-place and vision testing',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'web_bridge = chess_web_ui.web_bridge:main',
            'vision_game_node = chess_web_ui.vision_game_node:main',
        ],
    },
)

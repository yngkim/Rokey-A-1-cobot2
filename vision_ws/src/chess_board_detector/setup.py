from setuptools import find_packages, setup

package_name = 'chess_board_detector'

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
    description='Chess board corner detection and homography',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'board_detector_node = chess_board_detector.board_detector_node:main',
            'calibrate_corners = chess_board_detector.calibrate_corners:main',
            'capture_observe_frame = chess_board_detector.capture_observe_frame:main',
        ],
    },
)

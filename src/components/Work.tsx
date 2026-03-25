const projects = [
  {
    title: 'Minimalist Portfolio',
    category: 'Branding & Web Design',
    image:
      'https://images.pexels.com/photos/1779487/pexels-photo-1779487.jpeg?auto=compress&cs=tinysrgb&w=800',
  },
  {
    title: 'E-Commerce Platform',
    category: 'Full-Stack Development',
    image:
      'https://images.pexels.com/photos/1667088/pexels-photo-1667088.jpeg?auto=compress&cs=tinysrgb&w=800',
  },
  {
    title: 'SaaS Dashboard',
    category: 'UI/UX Design',
    image:
      'https://images.pexels.com/photos/196645/pexels-photo-196645.jpeg?auto=compress&cs=tinysrgb&w=800',
  },
  {
    title: 'Mobile App Design',
    category: 'Product Design',
    image:
      'https://images.pexels.com/photos/1092671/pexels-photo-1092671.jpeg?auto=compress&cs=tinysrgb&w=800',
  },
];

export default function Work() {
  return (
    <section id="work" className="py-24 bg-gray-900 text-white">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-5xl md:text-6xl font-serif mb-4">
            Selected Work
          </h2>
          <p className="text-lg text-gray-400 max-w-2xl mx-auto">
            A showcase of our recent projects and digital experiences
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-8">
          {projects.map((project, index) => (
            <div
              key={index}
              className="group relative overflow-hidden rounded-2xl aspect-[4/3] cursor-pointer"
            >
              <img
                src={project.image}
                alt={project.title}
                className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-110"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500">
                <div className="absolute bottom-0 left-0 right-0 p-8 transform translate-y-4 group-hover:translate-y-0 transition-transform duration-500">
                  <p className="text-emerald-400 text-sm font-medium mb-2">
                    {project.category}
                  </p>
                  <h3 className="text-2xl font-serif">{project.title}</h3>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

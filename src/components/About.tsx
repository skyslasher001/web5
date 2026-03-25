export default function About() {
  return (
    <section id="about" className="py-24 bg-gray-50">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="grid md:grid-cols-2 gap-16 items-center">
          <div className="relative">
            <div className="aspect-square rounded-2xl overflow-hidden shadow-2xl">
              <img
                src="https://images.pexels.com/photos/6373305/pexels-photo-6373305.jpeg?auto=compress&cs=tinysrgb&w=800"
                alt="Design Philosophy"
                className="w-full h-full object-cover hover:scale-105 transition-transform duration-700"
              />
            </div>
            <div className="absolute -bottom-8 -right-8 w-64 h-64 bg-emerald-600/10 rounded-full blur-3xl"></div>
          </div>

          <div>
            <h2 className="text-5xl md:text-6xl font-serif text-gray-900 mb-6">
              Our Design
              <br />
              Philosophy
            </h2>
            <div className="space-y-6 text-gray-600 leading-relaxed">
              <p className="text-lg">
                At the heart of our innovation lies a commitment to crafting
                exceptional digital experiences that harmonize cutting-edge
                technology with timeless design principles.
              </p>
              <p className="text-lg">
                Our team of distinguished professionals is dedicated to
                transforming your vision into bespoke digital masterpieces,
                ensuring unparalleled quality and exclusivity at every juncture.
              </p>
              <p className="text-lg">
                We believe in the power of meticulous attention to detail,
                intuitive user experiences, and sophisticated visual
                presentation to create truly memorable digital products.
              </p>
            </div>
            <a
              href="#contact"
              className="inline-block mt-8 text-emerald-600 font-medium hover:text-emerald-700 transition-colors group"
            >
              Learn more about our approach
              <span className="inline-block ml-2 group-hover:translate-x-2 transition-transform">
                →
              </span>
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
